"""Run the local PaperGuide API without starting the independent TaskHost."""

import uvicorn

from paperguide.runtime.env_file import load_env_file


def main() -> None:
    """Start Uvicorn in factory mode using only lightweight API clients."""

    load_env_file()
    uvicorn.run(
        "paperguide.api.app:create_default_api_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
