from django.shortcuts import render, get_object_or_404
from django.http import Http404
import re
import time
import uuid
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

# Global in-memory "database" to persist data between requests for the log viewer
SIMULATION_DB = {}

class ClassificationType(Enum):
    KNOWN_FLAKE = "Known Flake"
    INFRA_ERROR = "Infrastructure Error"
    PRODUCT_BUG = "New Product Bug"
    SETUP_FAILURE = "Setup Failure"
    ANSIBLE_DEPLOY_FAILURE = "Ansible Deploy Failure"
    OCP_MYSQL_VALIDATION_FAILURE = "ocp-mysql-validation-failure"
    OCP_MYSQL_CLEANUP_FAILURE = "ocp-mysql-cleanup-failure"
    OCP_MYSQL_DEPLOY_FAILURE = "ocp-mysql-deploy-failure"
    BACKUP_INTEGRITY_FAILURE = "Backup Integrity Failure"
    BACKUP_PARTIALLY_FAILED = "backup-partially-failed"
    BACKUP_SUCCESSFUL = "backup-successful"
    SKIP = "skip"
    NEW_SKIP = "new-skip"
    NEEDS_MANUAL_REVIEW = "Needs Manual Review"

@dataclass
class TestResult:
    test_name: str; suite: str; build_id: str; environment: str; logs: str
    oadp_version: str; repository: str; env_platform: str
    tags: List[str] = field(default_factory=list)
    test_run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rerun_count: int = 0
    steps: List[str] = field(default_factory=list)
    failed_step: Optional[str] = None
    analysis: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ClassificationResult:
    classifier_id: str; classification_type: ClassificationType; confidence: float
    details: Dict[str, Any] = field(default_factory=dict)

class ActionType(Enum):
    CREATE_JIRA_TICKET = "Create Jira Ticket"
    UPDATE_JIRA_TICKET = "Update Jira Ticket"
    NOTIFY_SLACK = "Notify Slack"
    MARK_FOR_RERUN = "Mark for Rerun"
    MARK_FOR_MANUAL_REVIEW = "Mark for Manual Review"
    RUN_CUSTOM_SCRIPT = "Run Custom Script"
    DO_NOTHING = "Do Nothing"

@dataclass
class ActionCommand:
    action_type: ActionType; payload: Dict[str, Any]

def parse_ginkgo_steps(logs: str) -> (List[str], Optional[str]):
    """Parses Ginkgo STEPs from logs and identifies the last one before a failure."""
    all_steps = re.findall(r"STEP: (.*)", logs)
    
    ignore_list = ["setting up environment", "cleaning up resources", "starting test"]
    filtered_steps = [s for s in all_steps if not any(ignore_phrase in s.lower() for ignore_phrase in ignore_list)]

    failure_keywords = ["FAIL", "panic", "error", "fatal"]
    last_step = "Log analysis did not find a failed step"
    
    log_lines = logs.split('\n')
    for i, line in enumerate(log_lines):
        if line.startswith("STEP:"):
            step_text = line.replace("STEP: ", "").strip()
            if not any(ignore_phrase in step_text.lower() for ignore_phrase in ignore_list):
                last_step = step_text
        
        if any(keyword in line.lower() for keyword in failure_keywords):
            break

    return filtered_steps, last_step

class DataContextService:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataContextService, cls).__new__(cls)
            cls._instance._db = SIMULATION_DB
        return cls._instance
    def save_test_result(self, result: TestResult): self._db[result.test_run_id] = result
    def get_test_result(self, test_run_id: str): return self._db.get(test_run_id)
    def update_analysis(self, test_run_id: str, analysis_data: Dict[str, Any]):
        if test_run_id in self._db: self._db[test_run_id].analysis.update(analysis_data)
    def get_all_results(self): return list(self._db.values())
    def clear(self): self._db.clear()

class ClassifierEngine:
    def __init__(self, data_service: DataContextService, flow_log: List[str]):
        self._data_service = data_service
        self.flow_log = flow_log
    
    def _step_based_classifier(self, test_name: str, failed_step: Optional[str]) -> List[ClassificationResult]:
        if not failed_step: return []
        found = []
        if "test_mysql_backup" in test_name and "Verify backup integrity" in failed_step:
            self.flow_log.append(f"   [Classifier] Match found: STEP_BACKUP_INTEGRITY")
            found.append(ClassificationResult("STEP_BACKUP_INTEGRITY", ClassificationType.BACKUP_INTEGRITY_FAILURE, 1.0, {"reason": "Checksum mismatch", "failed_step": failed_step}))
        return found

    def _regex_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        patterns = {
            "Connection timed out": ClassificationResult("REGEX_TIMEOUT", ClassificationType.KNOWN_FLAKE, 0.99, {"ticket": "PROJ-123"}),
            "database migration setup": ClassificationResult("REGEX_DB_MIGRATE", ClassificationType.SETUP_FAILURE, 0.95, {"error": "DB migration failed"}),
            "Test skipped due to unstable environment": ClassificationResult("REGEX_SKIP_ENV", ClassificationType.SKIP, 1.0, {"reason": "Unstable Environment"}),
        }
        for pattern, result in patterns.items():
            if re.search(pattern, logs, re.IGNORECASE):
                self.flow_log.append(f"   [Classifier] Match found: {result.classifier_id}")
                found.append(result)
        return found

    def _llm_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        if "nullpointerexception" in logs.lower():
            self.flow_log.append(f"   [Classifier] Match found: LLM_NPE (PRODUCT_BUG)")
            found.append(ClassificationResult("LLM_NPE", ClassificationType.PRODUCT_BUG, 0.92, {"exception": "NullPointerException"}))
        if "permission denied" in logs.lower():
            self.flow_log.append(f"   [Classifier] Match found: LLM_PERMS (INFRA_ERROR)")
            found.append(ClassificationResult("LLM_PERMS", ClassificationType.INFRA_ERROR, 0.88, {"error": "Permission denied"}))
        return found

    def classify(self, test_run_id: str) -> List[ClassificationResult]:
        test_result = self._data_service.get_test_result(test_run_id)
        if not test_result: return []
        self.flow_log.append(f"-> Classifying '{test_result.test_name}'...")
        
        all_classifications = (
            self._regex_classifier(test_result.logs) +
            self._llm_classifier(test_result.logs) +
            self._step_based_classifier(test_result.test_name, test_result.failed_step)
        )
        
        skip_classifications = [c for c in all_classifications if c.classification_type in [ClassificationType.SKIP, ClassificationType.NEW_SKIP]]
        if skip_classifications:
            self.flow_log.append(f"   [Classifier] Exclusive 'skip' classification found. Overriding others.")
            return [skip_classifications[0]]

        if not all_classifications:
            self.flow_log.append(f"   [Classifier] No specific match. Defaulting to Needs Manual Review.")
            return [ClassificationResult("DEFAULT_REVIEW", ClassificationType.NEEDS_MANUAL_REVIEW, 0.5, {})]
        
        unique = {c.classifier_id: c for c in all_classifications}
        return sorted(list(unique.values()), key=lambda x: x.confidence, reverse=True)

class DecisionEngine:
    def __init__(self, classifier: ClassifierEngine, data_service: DataContextService, flow_log: List[str]):
        self._classifier, self._data_service = classifier, data_service
        self.flow_log = flow_log

    def process_test_result(self, test_result: TestResult):
        all_steps, failed_step = parse_ginkgo_steps(test_result.logs)
        test_result.steps, test_result.failed_step = all_steps, failed_step
        self._data_service.save_test_result(test_result)
        
        classifications = self._classifier.classify(test_result.test_run_id)
        self.flow_log.append(f"   [DecisionEngine] Received {len(classifications)} classification(s). Applying rules...")
        action_commands = self._apply_rules(test_result, classifications)
        self._data_service.update_analysis(test_result.test_run_id, {
            "classifications": [asdict(c) for c in classifications],
            "actions": [asdict(a) for a in action_commands]
        })
        return action_commands

    def _apply_rules(self, test: TestResult, classifications: List[ClassificationResult]) -> List[ActionCommand]:
        actions = []
        primary_classification = classifications[0] if classifications else None

        if primary_classification and primary_classification.classification_type in [ClassificationType.SKIP, ClassificationType.NEW_SKIP]:
            self.flow_log.append(f"   [DecisionEngine] Rule matched: Skip test. Action: Do Nothing.")
            return [ActionCommand(ActionType.DO_NOTHING, {})]

        for c in classifications:
            if c.classification_type == ClassificationType.PRODUCT_BUG:
                actions.append(ActionCommand(ActionType.CREATE_JIRA_TICKET, {"test_name": test.test_name}))
            elif c.classification_type == ClassificationType.BACKUP_INTEGRITY_FAILURE:
                 actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#storage-team", "details": c.details}))
            elif c.classification_type == ClassificationType.KNOWN_FLAKE:
                actions.append(ActionCommand(ActionType.MARK_FOR_RERUN, {"reason": "Known flaky test"}))
            elif c.classification_type == ClassificationType.INFRA_ERROR:
                 actions.append(ActionCommand(ActionType.RUN_CUSTOM_SCRIPT, {"script_path": "/scripts/cleanup_stale_resources.sh"}))
                 actions.append(ActionCommand(ActionType.MARK_FOR_MANUAL_REVIEW, {"reason": "Infrastructure instability"}))

        if not actions:
            actions.append(ActionCommand(ActionType.MARK_FOR_MANUAL_REVIEW, {"reason": "No specific rule matched"}))

        unique_actions = {a.action_type: a for a in actions}
        return list(unique_actions.values())

class ActionExecutor:
    def __init__(self, flow_log: List[str]):
        self.flow_log = flow_log

    def execute_action(self, command: ActionCommand) -> Dict:
        action_type = command.action_type
        self.flow_log.append(f"   [ActionExecutor] Executing: {action_type.value}")
        payload = {"action_type": action_type.value}

        if action_type == ActionType.CREATE_JIRA_TICKET:
            payload.update({"status": "SUCCESS", "ticket_id": f"PROJ-{uuid.uuid4().hex[:4].upper()}"})
        elif action_type == ActionType.NOTIFY_SLACK:
            payload.update({"status": "SUCCESS", "message_sent_to": command.payload.get("channel", "#default")})
        elif action_type == ActionType.RUN_CUSTOM_SCRIPT:
            script_path = command.payload.get("script_path")
            payload.update({
                "status": "SUCCESS",
                "script": script_path,
                "logs": f"Executing {script_path}...\nConnecting to cluster...\nFound 3 stale pods.\nPod 'test-pod-123' deleted.\nPod 'test-pod-456' deleted.\nPod 'test-pod-789' deleted.\nScript finished.",
                "artifacts": {"report_url": f"http://artifacts.example.com/cleanup/{uuid.uuid4().hex[:8]}.html"}
            })
        else:
            payload.update({"status": "INFO", "message": f"Action '{action_type.value}' recorded."})
        
        return payload

def run_full_simulation():
    flow_log = ["🚀 Starting new simulation run..."]
    data_service = DataContextService(); data_service.clear()
    classifier_engine = ClassifierEngine(data_service, flow_log)
    decision_engine = DecisionEngine(classifier_engine, data_service, flow_log)
    action_executor = ActionExecutor(flow_log)

    ansible_error_log = "Error during command execution: ansible-playbook error: one or more host failed... use_role\\\":\\\".../roles/ocp-mysql-deploy\\\""
    ginkgo_log = "STEP: Setting up environment\nSTEP: Deploying application stack\nSTEP: Running backup for mysql-persistent\nSTEP: Verify backup integrity\nFAIL: Checksum mismatch for file /backup/data/db.sql"
    infra_log = "STEP: Launching new VM\nERROR: Request failed, permission denied when creating security group."

    tests = [
        TestResult("test_full_checkout_multi_error", "E2E", "build-503", "staging", "WARN: Connection timed out... FATAL: NullPointerException", "1.3.0", "stage", "AZURE", ["p1"]),
        TestResult("test_mysql_backup_and_verify", "DB-Backup", "build-507", "prod", ginkgo_log, "1.4.1", "main", "GCP", ["db", "critical"]),
        TestResult("test_vm_provisioning_error", "Infra", "build-511", "ci", infra_log, "1.5.0", "main", "vSphere", ["provisioning"]),
        TestResult("test_feature_x_flow", "Feature-Flags", "build-513", "dev", "STEP: Checking feature flag\nINFO: Skipping test, feature flag is disabled", "1.5.0", "feature-x", "KIND", ["feature-toggle"]),
    ]
    
    for test in tests:
        flow_log.append(f"--- Processing Test: {test.test_name} ---")
        action_commands = decision_engine.process_test_result(test)
        action_results = [action_executor.execute_action(cmd) for cmd in action_commands]
        data_service.update_analysis(test.test_run_id, {"action_results": action_results})
    
    flow_log.append("✅ Simulation complete.")
    
    final_results = []
    for result in data_service.get_all_results():
        result_dict = asdict(result)
        if 'analysis' in result_dict and result_dict['analysis']:
            if 'classifications' in result_dict['analysis']:
                for c in result_dict['analysis']['classifications']:
                    if isinstance(c.get('classification_type'), Enum): c['classification_type'] = c['classification_type'].value
            if 'actions' in result_dict['analysis']:
                for a in result_dict['analysis']['actions']:
                    if isinstance(a.get('action_type'), Enum): a['action_type'] = a['action_type'].value
        final_results.append(result_dict)
    return final_results, flow_log

def dashboard_view(request):
    test_results_data, flow_log = run_full_simulation()
    context = {
        'test_results': test_results_data,
        'flow_log': flow_log,
    }
    return render(request, 'analysis/dashboard.html', context)

def log_view(request, test_run_id):
    data_service = DataContextService()
    test_run = data_service.get_test_result(test_run_id)
    if not test_run: raise Http404("Test run not found")
    
    result_dict = asdict(test_run)
    if 'analysis' in result_dict:
        if 'classifications' in result_dict['analysis']:
            for c in result_dict['analysis']['classifications']:
                if isinstance(c.get('classification_type'), Enum): c['classification_type'] = c['classification_type'].value
                c['details_pretty'] = json.dumps(c.get('details', {}), indent=2)
        if 'actions' in result_dict['analysis']:
            for a in result_dict['analysis']['actions']:
                if isinstance(a.get('action_type'), Enum): a['action_type'] = a['action_type'].value
    
    context = {'run': result_dict}
    return render(request, 'analysis/log_viewer.html', context)

def manage_view(request):
    context = {
        'classification_types': sorted([e.value for e in ClassificationType]),
        'action_types': sorted([e.value for e in ActionType])
    }
    return render(request, 'analysis/manage.html', context)
