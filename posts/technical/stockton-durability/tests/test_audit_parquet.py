"""Tests for audit_parquet.py — zero-rate thresholds, invariants, HTML sampling.

Covers issue #72 (partial zero-rate regressions + cross-column invariants)
and issue #71 (_sample_html_parse must sample players from the parquet under
audit instead of hardcoding Stockton).
"""

import pandas as pd

import audit_parquet
import fetch_quarter_splits as fqs


def _clean_df(n: int = 12) -> pd.DataFrame:
    """A parquet-shaped frame that should audit clean."""
    return pd.DataFrame(
        {
            "quarter": [str((i % 4) + 1) for i in range(n)],
            "FT": [1] * n,
            "FTA": [2] * n,
            "FGA": [5] * n,
            "PTS": [10] * n,
            "TS_pct": [0.5] * n,
        }
    )


class TestAuditFileZeroThresholds:
    def test_clean_file_returns_zero_issues(self, tmp_path):
        path = tmp_path / "quarter_splits_clean.parquet"
        _clean_df().to_parquet(path)
        assert audit_parquet._audit_file(path) == 0

    def test_fga_zero_rate_above_90_flagged(self, tmp_path):
        # 19/20 rows have FGA == 0 (95% zero rate) — below 100%, so the old
        # all-zero check missed it (issue #72).
        df = _clean_df(20)
        df.loc[df.index[:19], "FGA"] = 0
        # Keep invariants satisfied on zero-FGA rows: PTS from free throws only
        df.loc[df.index[:19], ["FT", "FTA", "PTS"]] = [10, 10, 10]
        df.loc[df.index[:19], "TS_pct"] = 1.1
        path = tmp_path / "quarter_splits_fga.parquet"
        df.to_parquet(path)
        assert audit_parquet._audit_file(path) == 1

    def test_fga_all_zero_still_flagged(self, tmp_path):
        df = _clean_df(10)
        df["FGA"] = 0
        df[["FT", "FTA", "PTS"]] = 10
        df["TS_pct"] = 1.1
        path = tmp_path / "quarter_splits_allzero.parquet"
        df.to_parquet(path)
        assert audit_parquet._audit_file(path) == 1


class TestInvariants:
    def test_ft_exceeds_fta_flagged(self):
        df = _clean_df()
        df.loc[df.index[0], ["FT", "FTA"]] = [3, 2]
        assert audit_parquet._check_invariants(df) == 1

    def test_pts_exceeds_max_flagged(self):
        df = _clean_df()
        df.loc[df.index[0], "PTS"] = 3 * 5 + 1 + 1  # 3*FGA + FT + 1
        assert audit_parquet._check_invariants(df) == 1

    def test_ts_pct_out_of_range_flagged(self):
        df = _clean_df()
        df.loc[df.index[0], "TS_pct"] = 2.0
        assert audit_parquet._check_invariants(df) == 1

    def test_ts_pct_1_5_allowed(self):
        # A made 3 on a single FGA gives TS = 3 / (2*1) = 1.5 — legitimate.
        df = _clean_df()
        df.loc[df.index[0], ["FT", "FTA", "FGA", "PTS", "TS_pct"]] = [0, 0, 1, 3, 1.5]
        assert audit_parquet._check_invariants(df) == 0

    def test_nulls_do_not_count_as_violations(self):
        df = _clean_df()
        df.loc[df.index[0], ["FT", "FTA", "TS_pct"]] = [None, None, None]
        assert audit_parquet._check_invariants(df) == 0

    def test_clean_df_passes(self):
        assert audit_parquet._check_invariants(_clean_df()) == 0


def _triples_parquet(tmp_path, cache_dir, players):
    """Write a quarter_splits parquet + cached PBP HTML for the given players.

    Args:
        tmp_path: pytest tmp dir.
        cache_dir: directory standing in for HTML_CACHE.
        players: list of (player_id, player_name, game_id, quarter) tuples.

    Returns:
        Path to the written parquet.
    """
    rows = []
    for pid, name, gid, quarter in players:
        rows.append(
            {
                "player_id": pid,
                "player_name": name,
                "game_id": gid,
                "season": 1997,
                "age_regime": "test_regime",
                "quarter": quarter,
                "FT": 1,
                "FTA": 2,
                "FGA": 5,
                "PTS": 10,
                "TS_pct": 0.5,
            }
        )
        if quarter != "full":
            (cache_dir / f"{gid}_pbp.html").write_text("<html></html>", encoding="utf-8")
    path = tmp_path / "quarter_splits_test.parquet"
    pd.DataFrame(rows).to_parquet(path)
    return path


class TestSampleTriples:
    def test_samples_each_player_not_just_stockton(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        path = _triples_parquet(
            tmp_path,
            cache,
            [
                ("diawbo01", "Boris Diaw", "200501010SAS", "1"),
                ("nowitdi01", "Dirk Nowitzki", "200501020DAL", "1"),
            ],
        )
        sampled = audit_parquet._sample_triples([path], 10)
        assert set(sampled["player_name"]) == {"Boris Diaw", "Dirk Nowitzki"}

    def test_box_fallback_rows_excluded(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        path = _triples_parquet(
            tmp_path,
            cache,
            [
                ("stockjo01", "John Stockton", "199001010UTA", "full"),
                ("stockjo01", "John Stockton", "199701010UTA", "1"),
            ],
        )
        sampled = audit_parquet._sample_triples([path], 10)
        assert list(sampled["game_id"]) == ["199701010UTA"]

    def test_missing_cache_html_excluded(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        path = _triples_parquet(tmp_path, cache, [("diawbo01", "Boris Diaw", "200501010SAS", "1")])
        (cache / "200501010SAS_pbp.html").unlink()
        sampled = audit_parquet._sample_triples([path], 10)
        assert sampled.empty


class TestSampleHtmlParse:
    def test_parses_with_each_players_own_name(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        path = _triples_parquet(
            tmp_path,
            cache,
            [
                ("diawbo01", "Boris Diaw", "200501010SAS", "1"),
                ("nowitdi01", "Dirk Nowitzki", "200501020DAL", "1"),
            ],
        )

        calls = []

        def fake_parse(html, player_id, player_name, game_id, season, date, age_regime):
            calls.append((player_id, player_name, game_id))
            return [{"FT": 1, "FTA": 2, "FGA": 5, "PTS": 10, "AST": 1, "TOV": 1}]

        monkeypatch.setattr(fqs, "parse_pbp_quarters", fake_parse)
        issues = audit_parquet._sample_html_parse(10, [path])
        assert issues == 0
        assert ("diawbo01", "Boris Diaw", "200501010SAS") in calls
        assert ("nowitdi01", "Dirk Nowitzki", "200501020DAL") in calls
        assert all(name != "John Stockton" for _, name, _ in calls)

    def test_zero_rows_for_sampled_player_is_flagged(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        path = _triples_parquet(tmp_path, cache, [("diawbo01", "Boris Diaw", "200501010SAS", "1")])
        monkeypatch.setattr(fqs, "parse_pbp_quarters", lambda *a, **k: [])
        issues = audit_parquet._sample_html_parse(10, [path])
        # Zero rows for a player the parquet says has PBP rows = regression
        assert issues >= 1

    def test_no_matching_cache_skips_cleanly(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(audit_parquet, "HTML_CACHE", cache)
        assert audit_parquet._sample_html_parse(10, [tmp_path / "missing.parquet"]) == 0
