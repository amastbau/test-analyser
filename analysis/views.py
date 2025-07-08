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
    NEEDS_MANUAL_REVIEW = "Needs Manual Review"

@dataclass
class TestResult:
    test_name: str; suite: str; build_id: str; environment: str; logs: str
    oadp_version: str; repository: str; env_platform: str
    tags: List[str] = field(default_factory=list)
    test_run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rerun_count: int = 0
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
    def _regex_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        # Simple patterns
        simple_patterns = {
            "Connection timed out": ClassificationResult("REGEX_TIMEOUT", ClassificationType.KNOWN_FLAKE, 0.99, {"ticket": "PROJ-123"}),
            "database migration setup": ClassificationResult("REGEX_DB_MIGRATE", ClassificationType.SETUP_FAILURE, 0.95, {"error": "DB migration failed"}),
            "mysql validation failed": ClassificationResult("REGEX_MYSQL_VALIDATE", ClassificationType.OCP_MYSQL_VALIDATION_FAILURE, 0.96, {"reason": "Validation script returned non-zero"}),
            "mysql cleanup failed": ClassificationResult("REGEX_MYSQL_CLEANUP", ClassificationType.OCP_MYSQL_CLEANUP_FAILURE, 0.96, {"reason": "Cleanup script returned non-zero"}),
            "ocp-mysql deploy failed": ClassificationResult("REGEX_MYSQL_DEPLOY", ClassificationType.OCP_MYSQL_DEPLOY_FAILURE, 0.97, {"reason": "Deployment playbook failed"}),
        }
        for pattern, result in simple_patterns.items():
            if re.search(pattern, logs, re.IGNORECASE): found.append(result)

        # Advanced pattern with placeholder/dynamic data extraction
        ansible_match = re.search(r"ansible-playbook error: one or more host failed.*use_role\":\"([^\"]+)\"", logs, re.DOTALL)
        if ansible_match:
            failed_role = ansible_match.group(1).split('/')[-1] # Extract just the role name
            found.append(ClassificationResult(
                classifier_id="REGEX_ANSIBLE_FAILURE",
                classification_type=ClassificationType.ANSIBLE_DEPLOY_FAILURE,
                confidence=0.98,
                details={"failed_role": failed_role, "error_type": "Host Failed"}
            ))

        return found
    def _llm_classifier(self, logs: str) -> List[ClassificationResult]:
        found = []
        if "nullpointerexception" in logs.lower():
            found.append(ClassificationResult("LLM_NPE", ClassificationType.PRODUCT_BUG, 0.92, {"exception": "NullPointerException"}))
        if "permission denied" in logs.lower():
            found.append(ClassificationResult("LLM_PERMS", ClassificationType.INFRA_ERROR, 0.88, {"error": "Permission denied accessing resource"}))
        return found
    def classify(self, test_run_id: str) -> List[ClassificationResult]:
        test_result = self._data_service.get_test_result(test_run_id)
        if not test_result: return []
        all_classifications = self._regex_classifier(test_result.logs) + self._llm_classifier(test_result.logs)
        if not all_classifications:
            return [ClassificationResult("DEFAULT_REVIEW", ClassificationType.NEEDS_MANUAL_REVIEW, 0.5, {})]
        unique = {c.classifier_id: c for c in all_classifications}
        return sorted(list(unique.values()), key=lambda x: x.confidence, reverse=True)

class DecisionEngine:
    def __init__(self, classifier: ClassifierEngine, data_service: DataContextService):
        self._classifier, self._data_service = classifier, data_service
    def process_test_result(self, test_result: TestResult):
        self._data_service.save_test_result(test_result)
        classifications = self._classifier.classify(test_result.test_run_id)
        action_commands = self._apply_rules(test_result, classifications)
        self._data_service.update_analysis(test_result.test_run_id, {
            "classifications": [asdict(c) for c in classifications],
            "actions": [asdict(a) for a in action_commands]
        })
    def _apply_rules(self, test: TestResult, classifications: List[ClassificationResult]) -> List[ActionCommand]:
        actions = []
        for c in classifications:
            if c.classification_type == ClassificationType.KNOWN_FLAKE:
                actions.append(ActionCommand(ActionType.UPDATE_JIRA_TICKET, {"ticket": c.details["ticket"]}))
            if c.classification_type == ClassificationType.PRODUCT_BUG:
                actions.append(ActionCommand(ActionType.CREATE_JIRA_TICKET, {"test_name": test.test_name}))
                actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#dev-team"}))
            if c.classification_type == ClassificationType.INFRA_ERROR and test.rerun_count < 1:
                actions.append(ActionCommand(ActionType.RERUN_TEST, {}))
            if c.classification_type == ClassificationType.ANSIBLE_DEPLOY_FAILURE:
                actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#devops-ansible", "failed_role": c.details["failed_role"]}))
        if not actions:
            actions.append(ActionCommand(ActionType.NOTIFY_SLACK, {"channel": "#qa-triage"}))
        unique_actions = {a.action_type: a for a in actions}
        return list(unique_actions.values())

def run_full_simulation():
    data_service = DataContextService()
    data_service.clear() # Clear previous run's data
    classifier_engine = ClassifierEngine(data_service)
    decision_engine = DecisionEngine(classifier_engine, data_service)

    ansible_error_log = """
    {
        context: "(DefaultExecute::Execute)",
        message: "Error during command execution: ansible-playbook error: one or more host failed\n\nCommand executed:  /home/jenkins/ws/workspace/cam/oadp-1.4-tier1-tests/oadp-e2e-qe/.venv/bin/ansible-playbook --extra-vars {\\"namespace\\":\\"test-oadp-609\\",\\"use_role\\":\\"/home/jenkins/ws/workspace/cam/oadp-1.4-tier1-tests/oadp-e2e-qe/sample-applications/ocpdeployer/ansible/roles/ocp-mysql\\",\\"with_deploy\\":true} --connection local /home/jenkins/ws/workspace/cam/oadp-1.4-tier1-tests/oadp-e2e-qe/sample-applications/ansible/main.yml\n\nexit status 2",
        wrappedErrors: nil,
    }
    """

    tests = [
        TestResult("test_user_login_timeout", "Auth", "build-501", "staging", "ERROR: Connection timed out to auth-service", "1.2.3", "stage", "AWS_GCP", ["smoke"]),
        TestResult("test_calculate_invoice", "Billing", "build-501", "staging", "FATAL: java.lang.NullPointerException", "1.2.3", "stage", "AWS_GCP", ["p0"]),
        TestResult("test_api_create_user", "API", "build-502", "prod", "ERROR: Failed during database migration setup", "1.2.4", "prestage", "GCP_KUBEVIRT", ["smoke"]),
        TestResult("test_full_checkout_multi_error", "E2E", "build-503", "staging", "WARN: Connection timed out... FATAL: NullPointerException", "1.3.0", "stage", "AZURE", ["p1", "critical"]),
        TestResult("test_report_generation_perms", "Reporting", "build-504", "prod", "ERROR: Permission denied for user 'reporter' to database.", "1.3.1", "main", "AWS_RDS", ["p2"]),
        TestResult("test_ansible_role_deploy", "Deployment", "build-505", "ci", ansible_error_log, "1.4.0", "main", "OCP_BAREMETAL", ["deployment"]),
        TestResult("test_mysql_backup_validation", "Backup", "build-506", "ci", "mysql validation failed", "1.4.0", "main", "OCP_BAREMETAL", ["db"]),
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
        if 'actions' in result_dict['analysis']:
            for a in result_dict['analysis']['actions']:
                if isinstance(a.get('action_type'), Enum): a['action_type'] = a['action_type'].value
    
    # Format details for pretty printing in the template
    for c in result_dict.get('analysis', {}).get('classifications', []):
        c['details_pretty'] = json.dumps(c.get('details', {}), indent=2)

    context = {'run': result_dict}
    return render(request, 'analysis/log_viewer.html', context)

def manage_view(request):
    context = {
        'classification_types': [e.value for e in ClassificationType],
        'action_types': [e.value for e in ActionType]
    }
    return render(request, 'analysis/manage.html', context)
