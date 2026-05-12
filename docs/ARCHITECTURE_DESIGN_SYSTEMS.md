# Architectural Design Systems: Testing Workflows

This document defines the architectural systems for the three testing flows implemented in the project: **Deterministic**, **Hybrid (Ollama-Enhanced)**, and **Autonomous (Agentic)**.

---

## 1. Deterministic System (Core/Standard)
**Location:** `testing_workflow/`
**Primary Goal:** High-reliability, reproducible regression testing.

### Architecture
- **State Management:** Uses `WorkflowState` (TypedDict) for global run state and isolated `context_vars` for each virtual user.
- **Orchestration:** LangGraph `StateGraph` with linear node execution (`load_suite` -> `contract_validate` -> `prefetch_master_data` -> `execute_sample_workflow` -> `finalize_report`).
- **Execution Model:** `ThreadPoolExecutor` manages parallel virtual users. Each user executes a fixed sequence of steps from the JSON suite.
- **Data Strategy:** Rule-based generation (slugified names, timestamped emails, catalog-based companies).
- **Tooling:** Requests for HTTP, `render_value` for recursive template resolution, `json_path_get` for extraction and validation.

### Key Components
- `runner.py`: Bootstraps the LangGraph app.
- `execution.py`: Core parallel engine with thread-safe registry for peer interaction.
- `doctor_persona.py`: Template-based identity builder.

---

## 2. Hybrid System (Ollama-Enhanced)
**Location:** `testing_workflow_ollama/`
**Primary Goal:** Realistic, diverse test data and social content generation using Local LLMs.

### Architecture
- **Orchestration:** Extends the Deterministic flow with specialized LLM nodes.
- **LLM Integration:** Calls Ollama API (Llama 3.1) to generate realistic doctor personas (biographies, motivations, council boards) and social media content (posts, updates).
- **Image Generation:** Integrated Stable Diffusion (via `diffusers`) to generate profile and post images based on LLM-generated descriptions.
- **Data Strategy:** Combines deterministic seeds with LLM creative variance to ensure every virtual user is unique yet reproducible.

### Key Components
- `doctor_persona.py`: Adds `_request_openai_identity` (adaptable to Ollama) for rich persona metadata.
- `image_generation.py`: Wraps torch-based diffusion models for visual asset creation.

---

## 3. Autonomous System (Agentic Ollama)
**Location:** `testing_workflow_ollama_agentic/`
**Primary Goal:** Exploration of platform edge cases and self-healing journey paths.

### Architecture
- **State Management:** `AgenticWorkflowState` tracks global progress across autonomous agents.
- **Dynamic Planning:** Agents use a "Planner" (Ollama-powered) to decide their own sequence of actions based on their persona and motivation.
- **Self-Healing:** Agents can detect "Auth Mismatch" or "Missing Prerequisite" and automatically enqueue recovery actions (e.g., re-signing up or re-signing in).
- **Execution Model:** Session-based. Agents loop through a dynamic `action_plan` queue rather than a static step list.
- **Tooling:** `session.py` manages the agentic loop, followup logic, and prerequisite resolution.

### Key Components
- `session.py`: The "Brain" of the autonomous agent. Handles dynamic followup triggers (e.g., "If feed is empty, create a post").
- `graph.py`: Specialized graph for agentic sessions with real-time reporting.

---

## Comparison Table

| Feature | Deterministic | Hybrid (Ollama) | Autonomous (Agentic) |
| :--- | :--- | :--- | :--- |
| **Path Selection** | Static (JSON) | Static (JSON) | Dynamic (LLM Planned) |
| **Persona Data** | Template-based | LLM-generated | LLM-generated + Behavior Context |
| **Social Content** | Rule-based | LLM-generated | LLM-generated |
| **Visual Assets** | Placeholders | SD-generated | SD-generated |
| **Error Recovery** | Static Retries | Static Retries | Adaptive Re-planning |
| **Use Case** | Regression, CI/CD | Realistic Staging Tests | Exploratory, Load Bias |
