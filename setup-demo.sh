#!/bin/bash

# ==============================================================================
# Setup Script for Test Automation Analysis Demo (Django Version)
#
# This script generates a complete, runnable Django project with advanced features.
#
# Usage:
#   1. Save this script as 'setup_demo.sh'.
#   2. Make it executable: chmod +x setup_demo.sh
#   3. Run it: ./setup_demo.sh
#   4. After it runs, a 'test_analysis_project' directory will be created.
#   5. Navigate into the project: cd test_analysis_project
#   6. Install Django: pip install django
#   7. Run the development server: python manage.py runserver
#   8. Open your web browser to: http://127.0.0.1:8000/
# ==============================================================================

echo "🚀 Starting Django project setup..."

# --- Create Project Directory ---
PROJECT_NAME="test_analysis_project"
APP_NAME="analysis"
mkdir -p "$PROJECT_NAME/$PROJECT_NAME"
mkdir -p "$PROJECT_NAME/$APP_NAME/templates/$APP_NAME"

# --- 1. Create manage.py ---
echo "   -> Generating manage.py..."
cat > "$PROJECT_NAME/manage.py" << 'EOF'
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'test_analysis_project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
EOF
chmod +x "$PROJECT_NAME/manage.py"

# --- 2. Create settings.py ---
echo "   -> Generating $PROJECT_NAME/settings.py..."
cat > "$PROJECT_NAME/$PROJECT_NAME/settings.py" << 'EOF'
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = 'this-is-a-dummy-secret-key-for-the-demo'
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'analysis', # Our app
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'test_analysis_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'test_analysis_project.wsgi.application'

# We are not using a real database for this mock
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True
STATIC_URL = '/static/'
EOF

# --- 3. Create project urls.py ---
echo "   -> Generating $PROJECT_NAME/urls.py..."
cat > "$PROJECT_NAME/$PROJECT_NAME/urls.py" << 'EOF'
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('', include('analysis.urls')),
    path('admin/', admin.site.urls),
]
EOF

# --- 4. Create wsgi.py ---
echo "   -> Generating $PROJECT_NAME/wsgi.py..."
cat > "$PROJECT_NAME/$PROJECT_NAME/wsgi.py" << 'EOF'
"""
WSGI config for test_analysis_project project.
"""
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'test_analysis_project.settings')
application = get_wsgi_application()
EOF

# --- 5. Create app files (__init__.py, apps.py, urls.py) ---
echo "   -> Generating $APP_NAME application files..."
touch "$PROJECT_NAME/$PROJECT_NAME/__init__.py"
touch "$PROJECT_NAME/$APP_NAME/__init__.py"

cat > "$PROJECT_NAME/$APP_NAME/apps.py" << 'EOF'
from django.apps import AppConfig

class AnalysisConfig(AppConfig):
    name = 'analysis'
EOF

cat > "$PROJECT_NAME/$APP_NAME/urls.py" << 'EOF'
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('logs/<str:test_run_id>/', views.log_view, name='log_view'),
    path('manage/', views.manage_view, name='manage'),
]
EOF


# --- 6. Create views.py with all the simulation logic ---
echo "   -> Generating $APP_NAME/views.py..."
cat > "$PROJECT_NAME/$APP_NAME/views.py" << 'EOF'
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
EOF

# --- 7. Create the HTML templates ---
echo "   -> Generating HTML templates..."

# Dashboard Template
cat > "$PROJECT_NAME/$APP_NAME/templates/$APP_NAME/dashboard.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Analysis Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style> body { font-family: 'Inter', sans-serif; } </style>
</head>
<body class="bg-gray-900 text-gray-300">
    <nav class="bg-gray-800">
        <div class="container mx-auto px-4 md:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center">
                    <a href="{% url 'dashboard' %}" class="text-white font-bold text-xl">Analysis Dashboard</a>
                </div>
                <div class="flex items-center">
                    <a href="{% url 'manage' %}" class="text-gray-300 hover:bg-gray-700 hover:text-white px-3 py-2 rounded-md text-sm font-medium">Manage</a>
                </div>
            </div>
        </div>
    </nav>
    <div class="container mx-auto p-4 md:p-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-white">Test Failure Results</h1>
            <p class="text-gray-400">Results from the latest analysis run. Refresh the page to re-run the simulation.</p>
        </header>

        <div class="bg-gray-800 rounded-lg shadow-lg overflow-hidden">
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-700">
                    <thead class="bg-gray-700/50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Test Details</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Failed Step</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Classifications</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-gray-800 divide-y divide-gray-700">
                        {% for run in test_results %}
                            <tr class="hover:bg-gray-700/50">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <a href="{% url 'log_view' run.test_run_id %}" class="text-sm font-medium text-indigo-400 hover:text-indigo-300">{{ run.test_name }}</a>
                                    <div class="text-xs text-gray-400">{{ run.env_platform }} | {{ run.oadp_version }}</div>
                                </td>
                                <td class="px-6 py-4 text-sm text-yellow-400 truncate" style="max-width: 300px;" title="{{ run.failed_step|default:"N/A" }}">
                                    {{ run.failed_step|default:"N/A" }}
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex flex-col space-y-1">
                                        {% for c in run.analysis.classifications %}
                                            <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-900 text-blue-100" title="Confidence: {{ c.confidence|floatformat:2 }}">{{ c.classification_type }}</span>
                                        {% empty %}
                                            <span class="text-xs text-gray-500">N/A</span>
                                        {% endfor %}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                                    {% for action in run.analysis.actions %}
                                        <span>{{ action.action_type }}{% if not forloop.last %}, {% endif %}</span>
                                    {% empty %}
                                        None
                                    {% endfor %}
                                </td>
                            </tr>
                        {% empty %}
                            <tr><td colspan="4" class="text-center py-12 text-gray-500">No test results found.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
EOF

# Log Viewer Template
cat > "$PROJECT_NAME/$APP_NAME/templates/$APP_NAME/log_viewer.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Log Viewer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style> body { font-family: 'Inter', sans-serif; } </style>
</head>
<body class="bg-gray-900 text-gray-300">
    <nav class="bg-gray-800">
        <div class="container mx-auto px-4 md:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center">
                    <a href="{% url 'dashboard' %}" class="text-white font-bold text-xl">Analysis Dashboard</a>
                </div>
                <div class="flex items-center">
                    <a href="{% url 'manage' %}" class="text-gray-300 hover:bg-gray-700 hover:text-white px-3 py-2 rounded-md text-sm font-medium">Manage</a>
                </div>
            </div>
        </div>
    </nav>
    <div class="container mx-auto p-4 md:p-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-white">Log Viewer: {{ run.test_name }}</h1>
            <p class="text-gray-400 text-xs mt-1">ID: {{ run.test_run_id }}</p>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-2">
                <div>
                    <h2 class="text-xl font-semibold text-white mb-4">Executed Steps</h2>
                    <div class="bg-gray-800 p-4 rounded-lg space-y-2 mb-8">
                        {% for step in run.steps %}
                            <p class="p-2 rounded {% if step == run.failed_step %} bg-red-900 text-red-200 {% else %} bg-gray-700/50 {% endif %}">
                                {{ step }}
                            </p>
                        {% empty %}
                            <p class="text-gray-500">No steps found in log.</p>
                        {% endfor %}
                    </div>
                </div>
                <div>
                    <h2 class="text-xl font-semibold text-white mb-4">Full Log</h2>
                    <pre class="w-full bg-black text-xs text-green-400 p-4 rounded-lg h-96 overflow-y-auto"><code>{{ run.logs }}</code></pre>
                </div>
            </div>
            <div>
                <h2 class="text-xl font-semibold text-white mb-4">Analysis Details</h2>
                <div class="bg-gray-800 p-4 rounded-lg space-y-4">
                    <div>
                        <h3 class="font-semibold text-white">Metadata</h3>
                        <p class="text-sm text-gray-400"><strong>Platform:</strong> {{ run.env_platform }}</p>
                        <p class="text-sm text-gray-400"><strong>Version:</strong> {{ run.oadp_version }}</p>
                        <p class="text-sm text-gray-400"><strong>Repository:</strong> {{ run.repository }}</p>
                    </div>
                    <div>
                        <h3 class="font-semibold text-white">Tags</h3>
                        <div class="flex flex-wrap gap-2 mt-2">
                            {% for tag in run.tags %}
                                <span class="bg-gray-700 text-xs font-medium px-2.5 py-0.5 rounded-full">{{ tag }}</span>
                            {% endfor %}
                        </div>
                    </div>
                    <div>
                        <h3 class="font-semibold text-white">Classifications</h3>
                        {% for c in run.analysis.classifications %}
                            <div class="mt-2 p-2 bg-gray-700/50 rounded">
                                <p class="text-sm font-medium">{{ c.classification_type }} ({{ c.confidence|floatformat:2 }})</p>
                                <p class="text-xs text-gray-500">ID: {{ c.classifier_id }}</p>
                                <pre class="mt-2 text-xs bg-gray-900 p-2 rounded-md whitespace-pre-wrap"><code>{{ c.details_pretty }}</code></pre>
                            </div>
                        {% endfor %}
                    </div>
                     <div>
                        <h3 class="font-semibold text-white">Actions Taken</h3>
                        <ul class="list-disc list-inside text-sm text-gray-400 mt-2">
                           {% for action in run.analysis.actions %}
                                <li>{{ action.action_type }}</li>
                           {% endfor %}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
EOF

# Manage Page Template
cat > "$PROJECT_NAME/$APP_NAME/templates/$APP_NAME/manage.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage System Definitions</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style> body { font-family: 'Inter', sans-serif; } </style>
</head>
<body class="bg-gray-900 text-gray-300">
    <nav class="bg-gray-800">
        <div class="container mx-auto px-4 md:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center">
                    <a href="{% url 'dashboard' %}" class="text-white font-bold text-xl">Analysis Dashboard</a>
                </div>
                <div class="flex items-center">
                    <a href="{% url 'manage' %}" class="text-gray-300 hover:bg-gray-700 hover:text-white px-3 py-2 rounded-md text-sm font-medium">Manage</a>
                </div>
            </div>
        </div>
    </nav>
    <div class="container mx-auto p-4 md:p-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-white">System Definitions</h1>
            <p class="text-gray-400">The list of possible classifications and actions defined in the system.</p>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h2 class="text-xl font-semibold text-white mb-4">Classification Types</h2>
                <div class="bg-gray-800 rounded-lg shadow-lg p-4 space-y-2">
                    {% for item in classification_types %}
                        <p class="p-2 bg-gray-700/50 rounded">{{ item }}</p>
                    {% endfor %}
                </div>
            </div>
            <div>
                <h2 class="text-xl font-semibold text-white mb-4">Action Types</h2>
                <div class="bg-gray-800 rounded-lg shadow-lg p-4 space-y-2">
                    {% for item in action_types %}
                        <p class="p-2 bg-gray-700/50 rounded">{{ item }}</p>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</body>
</html>
EOF

echo ""
echo "✅ Django project '$PROJECT_NAME' created successfully."
echo ""
echo "--- Next Steps ---"
echo "1. Navigate into the project: cd $PROJECT_NAME"
echo "2. Install Django: pip install django"
echo "3. Run the server: python manage.py runserver"
echo "4. Open your browser to: http://127.0.0.1:8000/"
echo "------------------"

