"""
CLI runner for digest operations.
"""

import sys
import time
import logging

from digest.config import load_config
from digest.index_store import IndexStore
from digest.ingestion import IngestionOrchestrator
from digest.retrieval_service import RetrievalService
from digest.digest_builder import DigestBuilder
from digest.scheduler import DigestScheduler


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def run_ingestion(lookback_days: int = 7):
    """
    Run ingestion once.

    Args:
        lookback_days: Lookback window for initial ingestion
    """
    logger.info("Starting ingestion...")

    config = load_config()
    index_store = IndexStore(config)
    orchestrator = IngestionOrchestrator(config, index_store)

    stats = orchestrator.run_ingestion(lookback_days=lookback_days)

    logger.info(f"Ingestion completed:")
    logger.info(f"  Sources processed: {stats['sources_processed']}")
    logger.info(f"  Items fetched: {stats['items_fetched']}")
    logger.info(f"  Documents created: {stats['documents_created']}")
    logger.info(f"  Chunks created: {stats['chunks_created']}")
    logger.info(f"  Added: {stats['added']}")
    logger.info(f"  Updated: {stats['updated']}")
    logger.info(f"  Skipped: {stats['skipped']}")

    if stats['errors']:
        logger.error("Errors occurred:")
        for error in stats['errors']:
            logger.error(f"  {error}")


def run_digest_generation(topic_id: str = None, hours: int = 24):
    """
    Generate digests.

    Args:
        topic_id: Specific topic or None for all topics
        hours: Time window in hours
    """
    logger.info("Starting digest generation...")

    config = load_config()
    index_store = IndexStore(config)
    retrieval_service = RetrievalService(index_store, config)
    builder = DigestBuilder(retrieval_service)

    topics_to_process = [topic_id] if topic_id else list(config.topics.keys())

    for tid in topics_to_process:
        logger.info(f"Building digest for topic: {tid}")

        try:
            digest = builder.build_topic_digest(
                topic_id=tid,
                hours=hours
            )

            logger.info(f"Digest for {tid}:")
            logger.info(f"  Sources: {len(digest.source_digests)}")
            logger.info(f"  Consensus points: {len(digest.consensus_points)}")
            logger.info(f"  Divergences: {len(digest.divergence_points)}")
            logger.info(f"\nSummary:\n{digest.summary}\n")

        except Exception as e:
            logger.error(f"Error building digest for {tid}: {e}")


def run_scheduler():
    """Run the digest scheduler (daemon mode)."""
    logger.info("Starting digest scheduler...")

    scheduler = DigestScheduler()
    scheduler.start()

    logger.info("Scheduler running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping scheduler...")
        scheduler.stop()
        logger.info("Scheduler stopped")


def main():
    """Main CLI entrypoint."""
    if len(sys.argv) < 2:
        print("Usage: python digest/runner.py <command> [options]")
        print("Commands:")
        print("  ingest [days]     - Run ingestion once (default 7 days)")
        print("  digest [topic]    - Generate digest(s)")
        print("  schedule          - Start scheduler daemon")
        sys.exit(1)

    command = sys.argv[1]

    if command == "ingest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        run_ingestion(lookback_days=days)

    elif command == "digest":
        topic = sys.argv[2] if len(sys.argv) > 2 else None
        run_digest_generation(topic_id=topic)

    elif command == "schedule":
        run_scheduler()

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
