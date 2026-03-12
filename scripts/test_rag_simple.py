"""
Simple test script for RAG with explicit topics.
"""

import sys
sys.path.insert(0, "C:\\Users\\user\\Desktop\\selfhosted_assistant")

from digest.config import load_config
from digest.index_store import IndexStore
from digest.retrieval_service import RetrievalService
from digest.qa_handler import QAHandler


def main():
    print("Loading digest configuration...")
    config = load_config()

    print("Initializing index store...")
    index_store = IndexStore(config)

    print("Initializing retrieval service...")
    retrieval_service = RetrievalService(index_store, config)

    print("Initializing QA handler...")
    qa_handler = QAHandler(retrieval_service, gateway=None)

    # Test with explicit topic_id
    print(f"\n{'='*60}")
    print(f"Query: что думают авторы про нефть? (topic: investing)")
    print(f"{'='*60}")

    try:
        response = qa_handler.answer_question(
            "что думают авторы про нефть?",
            topic_id="investing"
        )

        print(f"\nAnswer: {response.answer}")
        print(f"Confidence: {response.confidence:.2%}")

        if response.evidence:
            print(f"\nEvidence ({len(response.evidence)} snippets):")
            for idx, evidence in enumerate(response.evidence[:5], 1):
                date_str = evidence.published_at.strftime('%d.%m.%Y')
                print(f"\n{idx}. {evidence.source_label} ({date_str})")
                print(f"   Score: {evidence.relevance_score:.3f}")
                print(f"   Text: {evidence.text[:150]}...")
        else:
            print("\nNo evidence found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    # Test with query that contains alias
    print(f"\n{'='*60}")
    print(f"Query: что нового на рынке? (contains 'рынок' alias)")
    print(f"{'='*60}")

    try:
        response = qa_handler.answer_question("что нового на рынке?")

        print(f"\nAnswer: {response.answer}")
        print(f"Confidence: {response.confidence:.2%}")

        if response.evidence:
            print(f"\nEvidence ({len(response.evidence)} snippets):")
            for idx, evidence in enumerate(response.evidence[:5], 1):
                date_str = evidence.published_at.strftime('%d.%m.%Y')
                print(f"\n{idx}. {evidence.source_label} ({date_str})")
                print(f"   Score: {evidence.relevance_score:.3f}")
                print(f"   Text: {evidence.text[:150]}...")
        else:
            print("\nNo evidence found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
