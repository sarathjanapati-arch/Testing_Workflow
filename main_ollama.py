import os

from testing_workflow.runner import run


if __name__ == "__main__":
    os.environ.setdefault("DOCTOR_IDENTITY_MODE", "ollama")
    run()
