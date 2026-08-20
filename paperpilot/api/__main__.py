"""Run the local PaperPilot API without starting the independent TaskHost."""

import uvicorn


def main() -> None:
    """Start Uvicorn in factory mode using only lightweight API clients."""

    uvicorn.run(
        "paperpilot.api.app:create_default_api_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
