from dataclasses import dataclass

from tools.common import logger
from tools.models import run_groq, run_ollama

from .router import ModelChoice, ModelRouter
from .task import NovaTask, TaskStatus


@dataclass(slots=True)
class OrchestratorResult:
    """Structured result returned by NOVA's orchestrator."""

    task_id: str
    selected_model: ModelChoice
    handled: bool
    output: str | None = None
    fallback_used: bool = False
    error: str | None = None


class NovaOrchestrator:
    """Route and execute substantial NOVA tasks."""

    def __init__(self) -> None:
        self.router = ModelRouter()

    async def execute(
        self,
        task: NovaTask,
    ) -> OrchestratorResult:
        """Execute a task using the appropriate model."""

        task.status = TaskStatus.RUNNING
        selected_model = self.router.choose_model(task)

        logger.info(
            "orchestrator task=%s selected_model=%s",
            task.task_id,
            selected_model.value,
        )

        # Normal conversation and simple desktop work remain
        # inside the Gemini Live session.
        if selected_model == ModelChoice.GEMINI:
            task.status = TaskStatus.COMPLETED

            return OrchestratorResult(
                task_id=task.task_id,
                selected_model=ModelChoice.GEMINI,
                handled=False,
            )

        try:
            fallback_used = False

            if selected_model == ModelChoice.GROQ:
                try:
                    output = await run_groq(task.request)

                except Exception:
                    logger.exception(
                        "Groq failed for task=%s; "
                        "trying Ollama fallback",
                        task.task_id,
                    )

                    output = await run_ollama(task.request)
                    selected_model = ModelChoice.OLLAMA
                    fallback_used = True

            else:
                output = await run_ollama(task.request)

            task.result = output
            task.status = TaskStatus.COMPLETED

            logger.info(
                "orchestrator completed task=%s "
                "model=%s fallback=%s",
                task.task_id,
                selected_model.value,
                fallback_used,
            )

            return OrchestratorResult(
                task_id=task.task_id,
                selected_model=selected_model,
                handled=True,
                output=output,
                fallback_used=fallback_used,
            )

        except Exception as error:
            task.status = TaskStatus.FAILED
            task.error = str(error)

            logger.exception(
                "orchestrator failed task=%s",
                task.task_id,
            )

            return OrchestratorResult(
                task_id=task.task_id,
                selected_model=selected_model,
                handled=True,
                error=(
                    "NOVA could not complete this task with "
                    f"{selected_model.value}."
                ),
            )