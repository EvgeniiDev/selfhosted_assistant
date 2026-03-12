"""
Tests for digest configuration loading and validation.
"""

import unittest
import json
import tempfile
from pathlib import Path

from digest.config import (
    load_config,
    get_source_by_id,
    get_sources_by_topic,
    get_topic_by_id,
    ConfigurationError
)


class DigestConfigTests(unittest.TestCase):
    """Test configuration loading and validation."""

    def test_load_valid_config(self):
        """Test loading a valid configuration file."""
        config_data = {
            "topics": {
                "test_topic": {
                    "label": "Test Topic",
                    "query_aliases": ["test", "topic"]
                }
            },
            "sources": [
                {
                    "source_id": "telegram:TestChannel",
                    "type": "telegram",
                    "slug": "TestChannel",
                    "topic_ids": ["test_topic"],
                    "enabled": True
                }
            ],
            "embedding_model": "intfloat/multilingual-e5-base",
            "chroma_path": "data/chroma",
            "state_path": "data/ingestion_state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)
            self.assertEqual(len(config.topics), 1)
            self.assertIn("test_topic", config.topics)
            self.assertEqual(config.topics["test_topic"].label, "Test Topic")
            self.assertEqual(len(config.sources), 1)
            self.assertEqual(config.sources[0].source_id, "telegram:TestChannel")
            self.assertEqual(config.embedding_model, "intfloat/multilingual-e5-base")
        finally:
            Path(temp_path).unlink()

    def test_missing_required_keys(self):
        """Test that missing required keys raise ConfigurationError."""
        config_data = {
            "topics": {},
            "sources": []
            # Missing other required keys
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            with self.assertRaises(ConfigurationError) as cm:
                load_config(temp_path)
            self.assertIn("Missing required config keys", str(cm.exception))
        finally:
            Path(temp_path).unlink()

    def test_invalid_source_type(self):
        """Test that invalid source type raises ConfigurationError."""
        config_data = {
            "topics": {
                "test_topic": {
                    "label": "Test Topic",
                    "query_aliases": ["test"]
                }
            },
            "sources": [
                {
                    "source_id": "invalid:Source",
                    "type": "invalid_type",  # Invalid type
                    "topic_ids": ["test_topic"],
                    "enabled": True
                }
            ],
            "embedding_model": "test-model",
            "chroma_path": "data/chroma",
            "state_path": "data/state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            with self.assertRaises(ConfigurationError) as cm:
                load_config(temp_path)
            self.assertIn("invalid type", str(cm.exception))
        finally:
            Path(temp_path).unlink()

    def test_source_references_unknown_topic(self):
        """Test that source referencing unknown topic raises ConfigurationError."""
        config_data = {
            "topics": {
                "test_topic": {
                    "label": "Test Topic",
                    "query_aliases": ["test"]
                }
            },
            "sources": [
                {
                    "source_id": "telegram:TestChannel",
                    "type": "telegram",
                    "slug": "TestChannel",
                    "topic_ids": ["unknown_topic"],  # Unknown topic
                    "enabled": True
                }
            ],
            "embedding_model": "test-model",
            "chroma_path": "data/chroma",
            "state_path": "data/state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            with self.assertRaises(ConfigurationError) as cm:
                load_config(temp_path)
            self.assertIn("unknown topics", str(cm.exception))
        finally:
            Path(temp_path).unlink()

    def test_get_source_by_id(self):
        """Test retrieving source by ID."""
        config_data = {
            "topics": {
                "test_topic": {
                    "label": "Test Topic",
                    "query_aliases": ["test"]
                }
            },
            "sources": [
                {
                    "source_id": "telegram:Channel1",
                    "type": "telegram",
                    "slug": "Channel1",
                    "topic_ids": ["test_topic"],
                    "enabled": True
                },
                {
                    "source_id": "telegram:Channel2",
                    "type": "telegram",
                    "slug": "Channel2",
                    "topic_ids": ["test_topic"],
                    "enabled": True
                }
            ],
            "embedding_model": "test-model",
            "chroma_path": "data/chroma",
            "state_path": "data/state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)
            source = get_source_by_id(config, "telegram:Channel1")
            self.assertIsNotNone(source)
            self.assertEqual(source.source_id, "telegram:Channel1")

            missing_source = get_source_by_id(config, "telegram:NonExistent")
            self.assertIsNone(missing_source)
        finally:
            Path(temp_path).unlink()

    def test_get_sources_by_topic(self):
        """Test retrieving sources by topic."""
        config_data = {
            "topics": {
                "investing": {
                    "label": "Investing",
                    "query_aliases": ["stocks"]
                },
                "business": {
                    "label": "Business",
                    "query_aliases": ["enterprise"]
                }
            },
            "sources": [
                {
                    "source_id": "telegram:Channel1",
                    "type": "telegram",
                    "slug": "Channel1",
                    "topic_ids": ["investing"],
                    "enabled": True
                },
                {
                    "source_id": "telegram:Channel2",
                    "type": "telegram",
                    "slug": "Channel2",
                    "topic_ids": ["investing", "business"],
                    "enabled": True
                },
                {
                    "source_id": "telegram:Channel3",
                    "type": "telegram",
                    "slug": "Channel3",
                    "topic_ids": ["business"],
                    "enabled": False  # Disabled
                }
            ],
            "embedding_model": "test-model",
            "chroma_path": "data/chroma",
            "state_path": "data/state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)

            # Should return only enabled sources
            investing_sources = get_sources_by_topic(config, "investing")
            self.assertEqual(len(investing_sources), 2)
            source_ids = [s.source_id for s in investing_sources]
            self.assertIn("telegram:Channel1", source_ids)
            self.assertIn("telegram:Channel2", source_ids)

            business_sources = get_sources_by_topic(config, "business")
            self.assertEqual(len(business_sources), 1)  # Channel3 is disabled
            self.assertEqual(business_sources[0].source_id, "telegram:Channel2")
        finally:
            Path(temp_path).unlink()

    def test_get_topic_by_id(self):
        """Test retrieving topic by ID."""
        config_data = {
            "topics": {
                "test_topic": {
                    "label": "Test Topic",
                    "query_aliases": ["test", "topic"]
                }
            },
            "sources": [],
            "embedding_model": "test-model",
            "chroma_path": "data/chroma",
            "state_path": "data/state.json",
            "digest_output_path": "data/digests"
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)
            topic = get_topic_by_id(config, "test_topic")
            self.assertIsNotNone(topic)
            self.assertEqual(topic.label, "Test Topic")

            missing_topic = get_topic_by_id(config, "nonexistent")
            self.assertIsNone(missing_topic)
        finally:
            Path(temp_path).unlink()

    def test_config_file_not_found(self):
        """Test that missing config file raises ConfigurationError."""
        with self.assertRaises(ConfigurationError) as cm:
            load_config("/nonexistent/path/config.json")
        self.assertIn("Configuration file not found", str(cm.exception))

    def test_invalid_json(self):
        """Test that invalid JSON raises ConfigurationError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name

        try:
            with self.assertRaises(ConfigurationError) as cm:
                load_config(temp_path)
            self.assertIn("Invalid JSON", str(cm.exception))
        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    unittest.main()
