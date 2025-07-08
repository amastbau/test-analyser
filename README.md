# Test Automation Auto-Analysis System

This project is a mock implementation of a sophisticated system designed to automatically analyze test automation failures. It ingests test results, classifies the root cause of failures using a pluggable engine, and determines the appropriate follow-up actions.

The primary goal is to reduce the manual effort required for triaging test failures, provide faster feedback to developers, and generate valuable insights into automation health.

## Architectural Overview

The system is designed as a modular, event-driven pipeline. This architecture ensures that components are decoupled, scalable, and can be updated independently. For example, the `Classifier Engine` can be swapped from a simple Regex-based model to a powerful LLM-based one with no impact on the rest of the system.

### Core Components

1.  **Ingestion Layer:** A dedicated API endpoint where CI/CD pipelines report test failures. It validates the incoming data (logs, metadata, artifacts) and publishes it as an event to a message queue.

2.  **Data & Context Service:** The central repository for all test-related data. It stores structured metadata (like test names, environments, and classifications) and links to large artifacts (like full logs and screenshots).

3.  **Classifier Engine (Pluggable):** The heart of the system. It analyzes the failure data to determine the root cause. This component is designed to be highly flexible:
    * **V1: Regex & Rule-Based:** The initial implementation uses fast, deterministic classifiers. This includes searching for specific error strings (e.g., "Connection timed out") and analyzing failed Ginkgo `STEP:` lines for context.
    * **V2: LLM-Based (The Evolution):** The system is designed to evolve by adding an LLM-based classifier. The flow would be:
        1.  First, try the fast Regex/Step-based classifiers.
        2.  If they fail to produce a high-confidence match, the system can **escalate the analysis** to a fine-tuned Large Language Model (LLM). This LLM would be trained on internal failure data to recognize complex and novel failure patterns that regex cannot handle.

4.  **Decision & Action Engine:** A configurable rules engine that takes the classification results and other metadata (e.g., environment type, rerun count) to decide on the appropriate actions. To make more intelligent decisions, it can also query external data sources.

5.  **Action Executor:** A set of workers that perform the actions determined by the Decision Engine, such as creating a Jira ticket, posting a Slack notification, or triggering a custom script.

### Architectural Diagram (Mermaid.js)

```mermaid
graph TD
    subgraph "External World"
        CICD("CI/CD Pipeline")
        Jira("Ticketing System")
        Slack("Notifier")
    end

    subgraph "Auto-Analysis System"
        IngestionAPI["Ingestion Layer"]
        MessageQueue["Message Queue"]
        
        subgraph "Classifier Engine (Pluggable)"
            direction TB
            ClassifierEngine["Orchestrator"]
            RegexClassifier{{"V1: Regex/Step Classifier"}}
            LLMClassifier{{"V2: LLM Classifier (Future)"}}
            ClassifierEngine --> RegexClassifier
            RegexClassifier -- "On No Match" --> LLMClassifier
        end

        DecisionEngine["Decision Engine (Rules)"]
        ActionExecutor["Action Executor"]
    end

    CICD -- "Reports Failure" --> IngestionAPI
    IngestionAPI -- "Publishes Event" --> MessageQueue
    MessageQueue --> DecisionEngine
    DecisionEngine -- "Requests Analysis" --> ClassifierEngine
    ClassifierEngine -- "Returns Classification" --> DecisionEngine
    DecisionEngine -- "Determines Actions" --> ActionExecutor
    ActionExecutor -- "Executes Actions" --> Jira
    ActionExecutor -- "Executes Actions" --> Slack
```

### Decision Engine Deep Dive

To make more intelligent decisions, the Decision Engine can be enhanced to query external systems for additional context. For example, before creating a new bug ticket, it could query Jira to see if a similar bug already exists for that component.

```mermaid
graph TD
    subgraph "Decision & Action Flow"
        A[Classification Result] --> DE{Decision Engine};
        DE -- "1. Need more context?" --> B(External Data Provider);
        B -- "e.g., Query Jira API" --> C{Jira};
        C -- "Returns existing bug info" --> B;
        B -- "2. Provides context" --> DE;
        DE -- "3. Applies Rules" --> D[Action Commands];
    end
```

## Integrating with InstructLab for AI Classification

The pluggable nature of the `Classifier Engine` is designed for a seamless evolution from a simple regex-based system to a sophisticated AI-driven one using tools like **InstructLab**.

InstructLab is a community-driven project that allows for significant contributions to Large Language Models (LLMs) with a much lower barrier to entry than traditional model training. Here’s how it can be used to implement the `V2: LLM Classifier` in our architecture:

### Step 1: Data Collection (The Feedback Loop)

The process begins by identifying failures that the current system cannot classify.

1.  Run the Django demo application.
2.  On the main dashboard, look for a test run where the only classification is **"Needs Manual Review"**.
3.  Click on the test name to go to the **Log Viewer** page.
4.  At the bottom of the page, you will find the **"Generate AI Training Data (InstructLab)"** section. This provides the exact template needed to teach the AI about this failure.

### Step 2: Initialize Your InstructLab Project

In your terminal, create a new directory for your InstructLab project and initialize it.

```bash
# This uses the Granite 7B model, a great starting point.
ilab init --model granite-7b-lab

# Navigate into the new directory
cd instructlab
```

### Step 3: Create a Taxonomy for Your Skills

A taxonomy is how you organize the knowledge you're adding. For our system, we can create a taxonomy for test failure classification.

```bash
ilab taxonomy new test_analysis.classification
```

This creates a `qna.yaml` file located at `taxonomy/test_analysis/classification/qna.yaml`. This file is where you will add your training examples.

### Step 4: Add the New Skill

This is where you use the data from the Django demo.

1.  Open the `taxonomy/test_analysis/classification/qna.yaml` file in a text editor.
2.  Copy the training data from the **Log Viewer** page in the demo.
3.  **Crucially, edit the `output` section** with the correct, human-verified analysis for that failure.

For example, if the unclassified failure was an `Unexpected token '<'` error, you would add the following entry to your `qna.yaml`:

```yaml
# taxonomy/test_analysis/classification/qna.yaml
---
version: 1
taxonomy:
- name: test_analysis
  description: Skills for analyzing test automation results
- name: classification
  description: Classifying specific test failures
  questions:
  -
    # This is the 'instruction' from the demo
    question: Classify the following test failure log based on the provided context.
    # This is the 'input' from the demo
    context: |
      Test Name: test_unclassified_failure
      Suite: GUI
      Failed Step: Clicking the 'Save' button

      --- LOGS ---
      ERROR: Unexpected token '<' at position 0
    # This is the 'output' that you, the human, provide
    answer: |
      {"classification": "New Product Bug", "component": "WebApp Frontend", "details": {"reason": "The server is returning HTML instead of JSON on API error, causing a client-side parsing failure."}}
```

### Step 5: Train and Test the Model Locally

Now, you can fine-tune the local LLM with your new knowledge.

1.  **Train the Model:** This command reads your `qna.yaml` files and fine-tunes the base model with the new skill.
    ```bash
    ilab train
    ```

2.  **Test the New Skill:** After training is complete, start a chat session with your newly trained model.
    ```bash
    ilab chat
    ```
    You can now test if it learned the new skill by pasting a similar log message. Your fine-tuned model should respond with the structured JSON classification you taught it. This model could then be deployed as the `V2: LLM Classifier` in our architecture.

This approach creates a powerful "flywheel effect": the more the system is used and the more manual triaging is done, the more data is collected to make the AI classifier smarter and more autonomous over time.

## Django Demo Implementation

This repository contains a fully runnable mock of the architecture using the Django web framework. It simulates the entire workflow in memory each time the dashboard is refreshed.

### Key Features of the Demo

* **Live Simulation:** Refreshing the dashboard re-runs the entire analysis pipeline with a predefined set of mock test failures.
* **Live Flow Log:** The dashboard includes a log panel that shows the step-by-step flow of the simulation, demonstrating how each component of the architecture is being used.
* **Ginkgo Step Parsing:** The system parses `STEP:` lines from logs to identify the exact point of failure, enabling more precise classification.
* **Multi-Classifier Support:** A single test failure can be matched by multiple classifiers (e.g., a Regex classifier and an LLM classifier), and the UI will display all findings.
* **Dynamic Data Extraction:** Classifiers can extract dynamic information (placeholders) from logs, such as a failed Ansible role name, and display it in the analysis details.
* **Action Execution with Results:** The simulation includes a mock `ActionExecutor` that "runs" the decided-upon actions and attaches the results (e.g., a mock script output or new Jira ticket ID) to the test run for viewing in the UI.
* **UI Pages:**
    * **Dashboard:** The main view showing the table of test failures and the live simulation log.
    * **Log Viewer:** A detailed page for each test run, showing metadata, all executed steps (with the failed step highlighted), full logs, and the results of any actions taken.
    * **Manage Page:** A simple page that lists all the Classifications and Actions currently defined in the system.

## How to Run the Demo

### Prerequisites

* Python 3.8+
* `pip` for installing packages
* Docker (for the containerized method)

### Method 1: Running Locally

1.  **Clone or Download the Project:**
    Ensure you have the `test_analysis_project` directory on your local machine.

2.  **Navigate to the Project Directory:**
    Open your terminal and change into the project's root directory.
    ```bash
    cd path/to/test_analysis_project
    ```

3.  **Create and Activate a Virtual Environment (Recommended):**
    ```bash
    # Create the virtual environment
    python -m venv env

    # Activate it
    # On macOS/Linux:
    source env/bin/activate
    # On Windows:
    # .\env\Scripts\activate
    ```

4.  **Install Dependencies:**
    Create a file named `requirements.txt` in the project root with the following content:
    ```
    django
    ```
    Then, run the installation command:
    ```bash
    pip install -r requirements.txt
    ```

5.  **Run the Web Server:**
    ```bash
    python manage.py runserver
    ```

6.  **View the Dashboard:**
    Open your web browser and navigate to:
    [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

### Method 2: Running with Docker

This is the easiest way to run the demo as it packages the application and its dependencies together.

1.  **Prerequisites:**
    * Ensure you have the `test_analysis_project` directory from the setup script.
    * Make sure you have Docker installed and running on your machine.

2.  **Create the `Dockerfile`:**
    In the root of the `test_analysis_project` directory (the same level as `manage.py`), create a file named `Dockerfile`. Copy the content from the provided `Dockerfile` artifact into this new file.

3.  **Create the `requirements.txt` file:**
    In the same directory, create a `requirements.txt` file with the following content:
    ```
    django
    ```

4.  **Build the Docker Image:**
    From your terminal, inside the `test_analysis_project` directory, run the following command. This will build the container image and tag it as `test-analysis-app`.
    ```bash
    docker build -t test-analysis-app .
    ```

5.  **Run the Docker Container:**
    After the build is complete, run the container with this command. It maps port 8000 on your local machine to port 8000 inside the container.
    ```bash
    docker run -p 8000:8000 test-analysis-app
    ```

6.  **View the Dashboard:**
    Open your web browser and navigate to:
    [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

## Future Enhancements

This demo provides a strong foundation. To evolve it into a production-ready system, the next steps would include:
* Replacing the in-memory database with a real one (e.g., PostgreSQL).
* Integrating a real message queue (e.g., RabbitMQ or Kafka).
* Building out the API integrations for Jira, Slack, and your CI/CD tool.
* Fine-tuning and deploying a real LLM for the advanced classification step.
* Adding a database-backed UI for managing classifiers and decision rules dynamically.
