"""Create the review project (project B), empty.

`monitor_run.py` fills it afterwards, run after run. The identifier
printed here is the one to pass to `--projet-revue`.
"""

import argparse

from _commun import settings
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.revue import create_project


def main() -> None:
    """Entry point of the review project creation script."""
    argparse.ArgumentParser(description=__doc__).parse_args()

    config = settings()
    kili = create_client(config)
    review_id = create_project(kili, config.review_project_title)
    logger.info(
        "Projet de revue prêt : {} — à passer à --projet-revue.", review_id
    )


if __name__ == "__main__":
    main()
