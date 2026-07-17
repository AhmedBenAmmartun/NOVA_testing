from enum import Enum

from .task import NovaTask, TaskType


class ModelChoice(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"
    OLLAMA = "ollama"


class ModelRouter:
    """Choose the best model for a NOVA task."""

    def choose_model(self, task: NovaTask) -> ModelChoice:
        """Return the model that should handle the task."""

        # Respect an explicit model request.
        if task.preferred_model:
            preferred = task.preferred_model.lower().strip()

            try:
                return ModelChoice(preferred)
            except ValueError:
                pass

        # Private information should remain local.
        if task.contains_private_data:
            return ModelChoice.OLLAMA

        # Explicit offline/private tasks go to Ollama.
        if task.task_type in {
            TaskType.PRIVATE,
            TaskType.OFFLINE,
        }:
            return ModelChoice.OLLAMA

        # Coding and heavier analysis go to Groq.
        if task.task_type in {
            TaskType.CODING,
            TaskType.ANALYSIS,
            TaskType.RESEARCH,
        }:
            return ModelChoice.GROQ

        # Normal conversation and desktop commands stay with Gemini.
        return ModelChoice.GEMINI