#!/usr/bin/env python3
"""Test discovery routes."""
import asyncio
import sys
from beets_flask.server.routes.discovery import (
    _deemix_settings, _slskd_settings
)
from beets_flask.discovery.providers import slskd

async def test_discovery():
    """Test the discovery endpoint."""
    print("Testing discovery configuration...")
    
    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    
    print(f"✓ deemix config:")
    print(f"  - base_url={dcfg['base_url']}")
    print(f"  - timeout={dcfg['timeout_seconds']}s")
    
    print(f"\n✓ slskd config:")
    print(f"  - base_url={scfg['base_url']}")
    print(f"  - api_key={'SET (' + scfg['api_key'][:10] + '...)' if scfg['api_key'] else 'NOT SET'}")
    print(f"  - ranking_mode={scfg['ranking_mode']}")
    print(f"  - min_bitrate_kbps={scfg['min_bitrate_kbps']}")
    
    print(f"\n✓ Testing slskd search...")
    try:
        candidates = await slskd.search_album(
            base_url=scfg['base_url'],
            api_key=scfg['api_key'],
            artist="Radiohead",
            album="OK Computer",
            timeout_seconds=30
        )
        print(f"  - Found {len(candidates)} candidates")
        if candidates:
            ranked = slskd.rank_candidates(candidates, ranking_mode=scfg['ranking_mode'], min_bitrate_kbps=scfg['min_bitrate_kbps'])
            print(f"  - Top 3 ranked candidates:")
            for i, c in enumerate(ranked[:3], 1):
                score = slskd.score_candidate(c, ranking_mode=scfg['ranking_mode'], min_bitrate_kbps=scfg['min_bitrate_kbps'])
                print(f"    {i}. {c['filename'][:60]} (score: {score:.2f})")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_discovery())
    sys.exit(0 if result else 1)
