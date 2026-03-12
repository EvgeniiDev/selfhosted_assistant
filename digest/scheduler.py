"""
Scheduler for automated digest ingestion and generation.
"""

import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from digest.config import load_config
from digest.index_store import IndexStore
from digest.ingestion import IngestionOrchestrator
from digest.retrieval_service import RetrievalService
from digest.digest_builder import DigestBuilder


logger = logging.getLogger(__name__)


class DigestScheduler:
    """
    Automated scheduler for digest jobs.

    Runs:
    - Periodic ingestion (hourly)
    - Daily digest generation
    - Optional publishing to Telegram
    """

    def __init__(self):
        """Initialize digest scheduler."""
        self.config = load_config()
        self.scheduler = BackgroundScheduler()
        self.is_running = False

        # Initialize components
        self.index_store = IndexStore(self.config)
        self.ingestion_orchestrator = IngestionOrchestrator(
            config=self.config,
            index_store=self.index_store
        )

        self.retrieval_service = RetrievalService(
            index_store=self.index_store,
            config=self.config
        )

        self.digest_builder = DigestBuilder(
            retrieval_service=self.retrieval_service
        )

    def start(self):
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        # Schedule ingestion job
        self.scheduler.add_job(
            func=self._run_ingestion,
            trigger=IntervalTrigger(minutes=self.config.ingestion_interval_minutes),
            id='ingestion_job',
            name='Periodic ingestion',
            replace_existing=True
        )

        # Schedule digest generation
        self.scheduler.add_job(
            func=self._run_digest_generation,
            trigger=CronTrigger.from_crontab(self.config.digest_schedule),
            id='digest_job',
            name='Daily digest generation',
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True
        logger.info("Digest scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self.is_running:
            return

        self.scheduler.shutdown()
        self.is_running = False
        logger.info("Digest scheduler stopped")

    def _run_ingestion(self):
        """Run ingestion job."""
        try:
            logger.info("Starting ingestion job...")
            stats = self.ingestion_orchestrator.run_ingestion()
            logger.info(f"Ingestion completed: {stats}")
        except Exception as e:
            logger.error(f"Ingestion job failed: {e}", exc_info=True)

    def _run_digest_generation(self):
        """Run digest generation job."""
        try:
            logger.info("Starting digest generation...")

            # Generate digests for all topics
            for topic_id in self.config.topics.keys():
                digest = self.digest_builder.build_topic_digest(
                    topic_id=topic_id,
                    hours=24
                )

                # Save digest
                self._save_digest(topic_id, digest)

            logger.info("Digest generation completed")

        except Exception as e:
            logger.error(f"Digest generation failed: {e}", exc_info=True)

    def _save_digest(self, topic_id: str, digest):
        """Save generated digest to file."""
        output_dir = Path(self.config.digest_output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"{topic_id}_{date_str}.txt"
        filepath = output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(digest.summary)

        logger.info(f"Saved digest to {filepath}")
