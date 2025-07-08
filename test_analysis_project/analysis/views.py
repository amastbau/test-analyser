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
    RERUN_TEST = "Rerun Test"
    CREATE_JIRA_TICKET = "Create Jira Ticket"
    UPDATE_JIRA_TICKET = "Update Jira Ticket"
    NOTIFY_SLACK = "Notify Slack"
    DO_NOTHING = "Do Nothing"

@dataclass
class ActionCommand:
    action_type: ActionType; payload: Dict[str, Any]

def parse_ginkgo_steps(logs: str) -> (List[str], Optional[str]):
    """Parses Ginkgo STEPs from logs and identifies the last one before a failure."""
    all_steps = re.findall(r"STEP: (.*)", logs)
    
    # Define steps to ignore as they are usually not the cause of a failure
    ignore_list = ["setting up environment", "cleaning up resources", "starting test"]
    filtered_steps = [s for s in all_steps if not any(ignore_phrase in s.lower() for ignore_phrase in ignore_list)]

    # Find the last step before a common failure indicator
    failure_keywords = ["FAIL", "panic", "error", "fatal"]
    last_step = None
    
    log_lines = logs.split('\n')
    for i, line in enumerate(log_lines):
        if line.startswith("STEP:"):
            step_text = line.replace("STEP: ", "").strip()
            if not any(ignore_phrase in step_text.lower() for ignore_phrase in ignore_list):
                last_step = step_text
        
        if any(keyword in line.lower() for keyword in failure_keywords):
            # If we find a failure keyword, the last valid step we saw is likely the failed one.
            break # Stop searching after the first failure indication

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
    def __init__(self, data_service: DataContextService): self._data_service = data_service
    
    def _step_based_classifier(self, test_name: str, failed_step: Optional[str]) -> List[ClassificationResult]:
        """Classifies based on the combination of test name and the failed step."""
        if not failed_step:
            return []
        
        found = []
        # Example of a highly specific classifier
        if "test_mysql_backup" in test_name and "Verify backup integrity" in failed_step:
            found.append(ClassificationResult(
                classifier_id="STEP_BACKUP_INTEGRITY",
                classification_type=ClassificationType.BACKUP_INTEGRITY_FAILURE,
                confidence=1.0,
                details={"reason": "Checksum mismatch on restored data", "failed_step": failed_step}
            ))
        return found

    def _regex_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        simple_patterns = {
            "Connection timed out": ClassificationResult("REGEX_TIMEOUT", ClassificationType.KNOWN_FLAKE, 0.99, {"ticket": "PROJ-123"}),
            "database migration setup": ClassificationResult("REGEX_DB_MIGRATE", ClassificationType.SETUP_FAILURE, 0.95, {"error": "DB migration failed"}),
        }
        for pattern, result in simple_patterns.items():
            if re.search(pattern, logs, re.IGNORECASE): found.append(result)

        ansible_match = re.search(r"ansible-playbook error: one or more host failed.*use_role\":\"([^\"]+)\"", logs, re.DOTALL)
        if ansible_match:
            failed_role = ansible_match.group(1).split('/')[-1]
            found.append(ClassificationResult("REGEX_ANSIBLE_FAILURE", ClassificationType.ANSIBLE_DEPLOY_FAILURE, 0.98, {"failed_role": failed_role}))
        return found

    def _llm_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        if "nullpointerexception" in logs.lower():
            found.append(ClassificationResult("LLM_NPE", ClassificationType.PRODUCT_BUG, 0.92, {"exception": "NullPointerException"}))
        if "permission denied" in logs.lower():
            found.append(ClassificationResult("LLM_PERMS", ClassificationType.INFRA_ERROR, 0.88, {"error": "Permission denied"}))
        return found

    def classify(self, test_run_id: str) -> List[ClassificationResult]:
        test_result = self._data_service.get_test_result(test_run_id)
        if not test_result: return []
        
        # Run all classifier types
        all_classifications = (
            self._regex_classifier(test_result.logs) +
            self._llm_classifier(test_result.logs) +
            self._step_based_classifier(test_result.test_name, test_result.failed_step)
        )

        if not all_classifications:
            return [ClassificationResult("DEFAULT_REVIEW", ClassificationType.NEEDS_MANUAL_REVIEW, 0.5, {})]
        
        unique = {c.classifier_id: c for c in all_classifications}
        return sorted(list(unique.values()), key=lambda x: x.confidence, reverse=True)

class DecisionEngine:
    def __init__(self, classifier: ClassifierEngine, data_service: DataContextService):
        self._classifier, self._data_service = classifier, data_service
    def process_test_result(self, test_result: TestResult):
        # First, parse steps from logs and update the test result object
        all_steps, failed_step = parse_ginkgo_steps(test_result.logs)
        test_result.steps = all_steps
        test_result.failed_step = failed_step
        self._data_service.save_test_result(test_result)
        
        # Now classify based on the full context
        classifications = self._classifier.classify(test_result.test_run_id)
        action_commands = self._apply_rules(test_result, classifications)
        self._data_service.update_analysis(test_result.test_run_id, {
            "classifications": [asdict(c) for c in classifications],
            "actions": [asdict(a) for a in action_commands]
        })
    def _apply_rules(self, test: TestResult, classifications: List[ClassificationResult]) -> List[ActionCommand]:
        actions = []
        for c in classifications:
            if c.classification_type == ClassificationType.PRODUCT_BUG:
                actions.append(ActionCommand(ActionType.CREATE_JIRA_TICKET, {"test_name": test.test_name}))
                actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#dev-team"}))
            elif c.classification_type == ClassificationType.BACKUP_INTEGRITY_FAILURE:
                 actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#storage-team", "details": c.details}))
            elif c.classification_type == ClassificationType.ANSIBLE_DEPLOY_FAILURE:
                actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#devops-ansible", "failed_role": c.details["failed_role"]}))
        if not actions:
            actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#qa-triage"}))
        unique_actions = {a.action_type: a for a in actions}
        return list(unique_actions.values())

def run_full_simulation():
    data_service = DataContextService()
    data_service.clear()
    classifier_engine = ClassifierEngine(data_service)
    decision_engine = DecisionEngine(classifier_engine, data_service)

    ansible_error_log = "Error during command execution: ansible-playbook error: one or more host failed... use_role\\\":\\\".../roles/ocp-mysql\\\""
    ginkgo_log = """
    STEP: Setting up environment
    STEP: Deploying application stack
    STEP: Running backup for mysql-persistent
    STEP: Verify backup integrity
    FAIL: Checksum mismatch for file /backup/data/db.sql
    """

    tests = [
        TestResult("test_user_login_timeout", "Auth", "build-501", "staging", "ERROR: Connection timed out to auth-service", "1.2.3", "stage", "AWS_GCP", ["smoke"]),
        TestResult("test_calculate_invoice", "Billing", "build-501", "staging", "FATAL: java.lang.NullPointerException", "1.2.3", "stage", "AWS_GCP", ["p0"]),
        TestResult("test_api_create_user", "API", "build-502", "prod", "ERROR: Failed during database migration setup", "1.2.4", "prestage", "GCP_KUBEVIRT", ["smoke"]),
        TestResult("test_full_checkout_multi_error", "E2E", "build-503", "staging", "WARN: Connection timed out... FATAL: NullPointerException", "1.3.0", "stage", "AZURE", ["p1", "critical"]),
        TestResult("test_ansible_role_deploy", "Deployment", "build-505", "ci", ansible_error_log, "1.4.0", "main", "OCP_BAREMETAL", ["deployment"]),
        TestResult("test_mysql_backup_and_verify", "DB-Backup", "build-507", "prod", ginkgo_log, "1.4.1", "main", "GCP", ["db", "critical"]),
    ]
    for test in tests:
        decision_engine.process_test_result(test)
    
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
    return final_results

def dashboard_view(request):
    test_results_data = run_full_simulation()
    context = {'test_results': test_results_data}
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
