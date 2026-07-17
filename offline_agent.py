import asyncio

from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

from tools.models import run_ollama


EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}


async def main() -> None:
    print("=" * 40)
    print("NOVA Offline Mode")
    print("Using local Ollama")
    print("Type /exit to stop")
    print("=" * 40)

    while True:
        try:
            prompt = await asyncio.to_thread(
                input,
                "\nAhmed: ",
            )
            prompt = prompt.strip()

            if not prompt:
                continue

            if prompt.lower() in EXIT_COMMANDS:
                print("NOVA: Offline mode closed.")
                break

            print("NOVA: Thinking locally...")

            try:
                response = await asyncio.wait_for(
                    run_ollama(prompt),
                    timeout=300,
                )
                print(f"\nNOVA: {response}")

            except TimeoutError:
                print(
                    "NOVA: Ollama took too long to respond."
                )

            except Exception as error:
                print(
                    "NOVA: Ollama could not answer. "
                    "Confirm Ollama is running and the "
                    "selected model is installed."
                )
                print(
                    f"Error type: {type(error).__name__}"
                )

        except (KeyboardInterrupt, EOFError):
            print("\nNOVA: Offline mode closed.")
            break


if __name__ == "__main__":
    asyncio.run(main())