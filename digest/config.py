"""
Configuration loading and validation for the digest system.
"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from digest.models import DigestConfig, TopicConfig, SourceConfig


DEFAULT_CONFIG_PATH = "digest_config.json"


class ConfigurationError(Exception):
    """Raised when configuration is invalid."""
    pass


def load_config(config_path: Optional[str] = None) -> DigestConfig:
    """
    Load and validate digest configuration from JSON file.

    Args:
        config_path: Path to config file. Defaults to digest_config.json in cwd.

    Returns:
        Validated DigestConfig instance

    Raises:
        ConfigurationError: If config is invalid or missing
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    config_file = Path(config_path)
    if not config_file.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in config file: {e}")
    except Exception as e:
        raise ConfigurationError(f"Error reading config file: {e}")

    return _parse_config(data)


def _parse_config(data: dict) -> DigestConfig:
    """
    Parse and validate configuration dictionary.

    Args:
        data: Raw configuration dictionary

    Returns:
        DigestConfig instance

    Raises:
        ConfigurationError: If configuration is invalid
    """
    # Validate required top-level keys
    required_keys = [
        "topics", "sources", "embedding_model", "chroma_path",
        "state_path", "digest_output_path"
    ]
    missing_keys = [k for k in required_keys if k not in data]
    if missing_keys:
        raise ConfigurationError(f"Missing required config keys: {missing_keys}")

    # Parse topics
    topics = {}
    if not isinstance(data["topics"], dict):
        raise ConfigurationError("'topics' must be a dictionary")

    for topic_id, topic_data in data["topics"].items():
        if not isinstance(topic_data, dict):
            raise ConfigurationError(f"Topic '{topic_id}' must be a dictionary")

        topics[topic_id] = TopicConfig(
            topic_id=topic_id,
            label=topic_data.get("label", topic_id),
            query_aliases=topic_data.get("query_aliases", [])
        )

    # Parse sources
    sources = []
    if not isinstance(data["sources"], list):
        raise ConfigurationError("'sources' must be a list")

    for idx, source_data in enumerate(data["sources"]):
        if not isinstance(source_data, dict):
            raise ConfigurationError(f"Source at index {idx} must be a dictionary")

        source_id = source_data.get("source_id")
        if not source_id:
            raise ConfigurationError(f"Source at index {idx} missing 'source_id'")

        source_type = source_data.get("type")
        if not source_type:
            raise ConfigurationError(f"Source '{source_id}' missing 'type'")

        if source_type not in ["telegram", "youtube"]:
            raise ConfigurationError(
                f"Source '{source_id}' has invalid type '{source_type}'. "
                f"Must be 'telegram' or 'youtube'"
            )

        topic_ids = source_data.get("topic_ids", [])
        if not isinstance(topic_ids, list):
            raise ConfigurationError(f"Source '{source_id}' topic_ids must be a list")

        # Validate topic_ids reference existing topics
        invalid_topics = [tid for tid in topic_ids if tid not in topics]
        if invalid_topics:
            raise ConfigurationError(
                f"Source '{source_id}' references unknown topics: {invalid_topics}"
            )

        sources.append(SourceConfig(
            source_id=source_id,
            type=source_type,
            topic_ids=topic_ids,
            enabled=source_data.get("enabled", True),
            slug=source_data.get("slug"),
            channel_id=source_data.get("channel_id")
        ))

    # Validate embedding model
    embedding_model = data["embedding_model"]
    if not isinstance(embedding_model, str) or not embedding_model:
        raise ConfigurationError("'embedding_model' must be a non-empty string")

    # Validate paths
    chroma_path = data["chroma_path"]
    state_path = data["state_path"]
    digest_output_path = data["digest_output_path"]

    # Parse optional parameters with defaults
    recent_window_hours = data.get("recent_window_hours", 36)
    source_profile_days = data.get("source_profile_days", 60)
    ingestion_interval_minutes = data.get("ingestion_interval_minutes", 60)
    digest_schedule = data.get("digest_schedule", "0 21 * * *")
    digest_chat_id = data.get("digest_chat_id")

    return DigestConfig(
        topics=topics,
        sources=sources,
        embedding_model=embedding_model,
        chroma_path=chroma_path,
        state_path=state_path,
        digest_output_path=digest_output_path,
        recent_window_hours=recent_window_hours,
        source_profile_days=source_profile_days,
        ingestion_interval_minutes=ingestion_interval_minutes,
        digest_schedule=digest_schedule,
        digest_chat_id=digest_chat_id
    )


def get_source_by_id(config: DigestConfig, source_id: str) -> Optional[SourceConfig]:
    """Get source configuration by source_id."""
    for source in config.sources:
        if source.source_id == source_id:
            return source
    return None


def get_sources_by_topic(config: DigestConfig, topic_id: str) -> list[SourceConfig]:
    """Get all sources that cover a specific topic."""
    return [s for s in config.sources if topic_id in s.topic_ids and s.enabled]


def get_topic_by_id(config: DigestConfig, topic_id: str) -> Optional[TopicConfig]:
    """Get topic configuration by topic_id."""
    return config.topics.get(topic_id)
