"""
Test script for querying the RAG system.
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

    # Test query about oil, VTB, and Iran
    queries = [
        "что думают авторы про нефть?",
        "что говорят про ВТБ?",
        "есть ли информация про Иран?"
    ]

    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        try:
            response = qa_handler.answer_question(query)

            print(f"\nAnswer: {response.answer}")
            print(f"Confidence: {response.confidence:.2%}")
            print(f"Needs clarification: {response.needs_clarification}")

            if response.evidence:
                print(f"\nEvidence ({len(response.evidence)} snippets):")
                for idx, evidence in enumerate(response.evidence[:3], 1):
                    date_str = evidence.published_at.strftime('%d.%m.%Y')
                    print(f"\n{idx}. {evidence.source_label} ({date_str})")
                    print(f"   Score: {evidence.relevance_score:.3f}")
                    print(f"   Text: {evidence.text[:200]}...")
            else:
                print("\nNo evidence found.")

            if response.sources:
                print(f"\nSources: {len(response.sources)}")
                for source in response.sources[:3]:
                    print(f"  - {source}")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
