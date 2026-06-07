#!/usr/bin/env python3
"""
Test script to verify the multi-source job search integration.
Tests the new SearchProvider that combines:
1. MCP Search Server (SearXNG)
2. LinkedIn Guest API
3. JSearch API (OpenWebNinja)
"""

import asyncio
import logging
import sys
import os

# Add the backend directory to the path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.agents.search_provider import provider
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

log = logging.getLogger(__name__)

async def test_search_provider():
    """Test the multi-source search provider."""
    print("=" * 60)
    print("Testing Multi-Source Job Search Provider")
    print("=" * 60)

    # Test query
    test_query = "python developer remote"
    print(f"\nTesting with query: '{test_query}'")
    print("-" * 40)

    try:
        # Perform search
        results = provider.search(test_query, num_results=5)

        print(f"\nSearch completed! Found {len(results)} total results:")
        print("-" * 40)

        for i, result in enumerate(results, 1):
            print(f"\nResult {i}:")
            print(f"  Title: {result.get('title', 'N/A')}")
            print(f"  URL: {result.get('url', 'N/A')}")
            print(f"  Source: {result.get('source', 'N/A')}")
            print(f"  Content: {result.get('content', 'N/A')[:100]}...")

        # Show configuration
        print("\n" + "=" * 60)
        print("Current Configuration:")
        print("=" * 60)
        print(f"LinkedIn Guest API Enabled: {getattr(settings, 'LINKEDIN_GUEST_API_ENABLED', False)}")
        print(f"JSearch API Key Configured: {bool(getattr(settings, 'JSEARCH_API_KEY', None))}")
        print(f"MCP Search URL: {settings.MCP_SEARCH_URL}")
        print(f"Search Max Results: {settings.SEARCH_MAX_RESULTS}")

        return len(results) > 0

    except Exception as e:
        log.error(f"Search test failed: {e}", exc_info=True)
        return False

def main():
    """Main test function."""
    print("Starting integration test...")

    # Run the async test
    success = asyncio.run(test_search_provider())

    print("\n" + "=" * 60)
    if success:
        print("✅ INTEGRATION TEST PASSED")
        print("The multi-source search provider is working correctly!")
    else:
        print("❌ INTEGRATION TEST FAILED")
        print("Please check the logs above for details.")
    print("=" * 60)

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())