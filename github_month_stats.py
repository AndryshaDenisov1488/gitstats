#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Статистика активности на GitHub за выбранный месяц:
коммиты, строки +/-, файлы (добавлены/изменены/удалены/переименованы),
репозитории, пуши (по публичной ленте событий, см. ограничения).

Требуется токен (PAT) для нормальных лимитов и доступа к приватным репам:
  set GITHUB_TOKEN=ghp_xxxx
  python github_month_stats.py AndryshaDenisov1488

Документация поиска коммитов:
https://docs.github.com/en/search-github/searching-on-github/searching-commits

Ограничения API:
- Поиск коммитов индексирует в основном дефолтную ветку; до ~1000 результатов на запрос.
- Лента событий публичная — максимум ~300 последних событий (пуши за весь месяц могут быть неполными).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API = "https://api.github.com"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """Inclusive start 00:00 UTC, exclusive end (first moment of next month)."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


def last_calendar_month(ref: date | None = None) -> tuple[datetime, datetime]:
    d = ref or utc_today()
    first_this = date(d.year, d.month, 1)
    last_prev = first_this - timedelta(days=1)
    return month_range(last_prev.year, last_prev.month)


def this_month_so_far(ref: date | None = None) -> tuple[datetime, datetime]:
    d = ref or utc_today()
    start, _ = month_range(d.year, d.month)
    end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)
    return start, end


def http_get(
    url: str,
    token: str | None,
    *,
    accept: str = "application/vnd.github+json",
) -> tuple[int, dict[str, str], Any]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-month-stats-script",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=60) as resp:
            status = resp.status
            rh = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8", errors="replace")
            if not body.strip():
                return status, rh, None
            return status, rh, json.loads(body)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body.strip() else None
        except json.JSONDecodeError:
            payload = {"raw": body}
        raise RuntimeError(f"HTTP {e.code} для {url}: {payload}") from e
    except URLError as e:
        raise RuntimeError(f"Сеть: {url}: {e}") from e


def parse_rate_limit(headers: dict[str, str]) -> tuple[int, int]:
    rem = int(headers.get("x-ratelimit-remaining", "0") or 0)
    reset = int(headers.get("x-ratelimit-reset", "0") or 0)
    return rem, reset


def sleep_until_reset(headers: dict[str, str]) -> None:
    _, reset = parse_rate_limit(headers)
    if reset:
        wake = datetime.fromtimestamp(reset, tz=timezone.utc) + timedelta(seconds=2)
        wait = max(0.0, (wake - datetime.now(timezone.utc)).total_seconds())
        if wait > 0:
            print(f"Лимит запросов, жду {wait:.0f} с…", file=sys.stderr)
            time.sleep(wait)


def iterate_search_commits(
    username: str,
    start: datetime,
    end: datetime,
    token: str | None,
    on_headers: Callable[[dict[str, str]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    author-date в поиске — по дате автора, диапазус [start, end] в днях UTC.
    """
    start_d = start.date().isoformat()
    # exclusive end: последний день включительно
    last_day = (end - timedelta(seconds=1)).date().isoformat()
    q = f"author:{username} author-date:{start_d}..{last_day}"
    page = 1
    per_page = 100
    total_reported = None

    while True:
        qs = urlencode({"q": q, "per_page": per_page, "page": page})
        url = f"{API}/search/commits?{qs}"
        status, headers, data = http_get(
            url,
            token,
            accept="application/vnd.github.cloak-preview+json",
        )
        if on_headers:
            on_headers(headers)

        if data is None:
            break
        total_reported = data.get("total_count", total_reported)
        items = data.get("items") or []
        if not items:
            break
        yield from items
        if len(items) < per_page:
            break
        page += 1
        if total_reported is not None and page * per_page >= 1000:
            print(
                "Внимание: у поиска коммитов GitHub потолок ~1000 результатов; "
                "статистика может быть усечённой.",
                file=sys.stderr,
            )
            break


def fetch_commit_detail(full_name: str, sha: str, token: str | None) -> dict[str, Any]:
    owner, repo = full_name.split("/", 1)
    url = f"{API}/repos/{quote(owner)}/{quote(repo)}/commits/{sha}"
    _, _, data = http_get(url, token)
    if not isinstance(data, dict):
        return {}
    return data


def scan_public_events(
    username: str,
    start: datetime,
    end: datetime,
    token: str | None,
) -> tuple[int, int, dict[str, int]]:
    """
    Публичная лента: пуши и счётчики по типу события за период.
    Обрезка ~300 событий — цифры ниже — только по «хвосту» ленты.
    """
    push_count = 0
    commits_in_pushes = 0
    by_type: dict[str, int] = defaultdict(int)
    page = 1
    per_page = 100

    while page <= 3:  # максимум 300 событий
        qs = urlencode({"per_page": per_page, "page": page})
        url = f"{API}/users/{quote(username)}/events/public?{qs}"
        _, _, events = http_get(url, token)
        if not isinstance(events, list) or not events:
            break
        for ev in events:
            created_raw = ev.get("created_at")
            if not created_raw:
                continue
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created < start:
                continue
            if created >= end:
                continue
            et = ev.get("type") or "Unknown"
            by_type[str(et)] += 1
            if et == "PushEvent":
                push_count += 1
                payload = ev.get("payload") or {}
                commits_in_pushes += int(payload.get("distinct_size") or payload.get("size") or 0)
        if len(events) < per_page:
            break
        page += 1

    return push_count, commits_in_pushes, dict(by_type)


@dataclass
class MonthStats:
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    files_touched: int = 0
    files_by_status: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    repos: set[str] = field(default_factory=set)
    shas: set[tuple[str, str]] = field(default_factory=set)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Большая статистика по GitHub за месяц (коммиты, строки, файлы, пуши).",
    )
    parser.add_argument("username", help="Логин GitHub, например AndryshaDenisov1488")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="PAT (или задайте GITHUB_TOKEN в окружении)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--last-month",
        action="store_true",
        help="Прошлый календарный месяц (по умолчанию)",
    )
    mode.add_argument(
        "--this-month",
        action="store_true",
        help="С 1-го числа текущего месяца по сегодня (UTC)",
    )
    parser.add_argument("--year", type=int, help="Год (с --month)")
    parser.add_argument("--month", type=int, help="Месяц 1..12 (с --year)")
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Не запрашивать детали коммитов (только число коммитов из поиска, без +/- строк)",
    )
    args = parser.parse_args()

    if args.year is not None or args.month is not None:
        if args.year is None or args.month is None:
            print("Нужны оба: --year и --month", file=sys.stderr)
            return 2
        start, end = month_range(args.year, args.month)
    elif args.this_month:
        start, end = this_month_so_far()
    else:
        start, end = last_calendar_month()

    token = args.token

    if not token:
        print(
            "Предупреждение: без GITHUB_TOKEN лимит 60 запросов/час; "
            "для полной статистики создайте PAT: "
            "https://github.com/settings/tokens",
            file=sys.stderr,
        )

    print(f"Пользователь: {args.username}")
    print(f"Период UTC: {start.isoformat()} .. {(end - timedelta(seconds=1)).isoformat()}")
    print()

    stats = MonthStats()

    def on_headers(h: dict[str, str]) -> None:
        rem, reset = parse_rate_limit(h)
        if rem <= 1:
            sleep_until_reset(h)

    for it in iterate_search_commits(args.username, start, end, token, on_headers=on_headers):
        repo = (it.get("repository") or {}).get("full_name")
        sha = it.get("sha")
        if repo and sha:
            stats.shas.add((repo, sha))
            stats.repos.add(repo)
    stats.commits = len(stats.shas)

    if not args.skip_details and stats.shas:
        done = 0
        total = len(stats.shas)
        for repo, sha in sorted(stats.shas):
            done += 1
            if done % 50 == 1 or done == total:
                print(f"Коммиты: детали {done}/{total}…", file=sys.stderr)
            try:
                detail = fetch_commit_detail(repo, sha, token)
            except RuntimeError as e:
                if "403" in str(e) or "429" in str(e):
                    time.sleep(60)
                    detail = fetch_commit_detail(repo, sha, token)
                else:
                    raise
            s = detail.get("stats") or {}
            stats.additions += int(s.get("additions") or 0)
            stats.deletions += int(s.get("deletions") or 0)
            stats.repos.add(repo)
            for f in detail.get("files") or []:
                stats.files_touched += 1
                st = (f.get("status") or "unknown").lower()
                stats.files_by_status[st] += 1

    push_count, commits_in_push_events, events_by_type = scan_public_events(
        args.username, start, end, token
    )

    total_delta = stats.additions + stats.deletions
    ratio = (stats.additions / stats.deletions) if stats.deletions else None

    print("=== Коммиты и код ===")
    print(f"  Уникальных коммитов (поиск): {stats.commits}")
    print(f"  Строк добавлено:  {stats.additions:,}")
    print(f"  Строк удалено:    {stats.deletions:,}")
    print(f"  Сумма изменений:  {total_delta:,}")
    if ratio is not None:
        print(f"  Отношение +/−:    {ratio:.2f}")
    print(f"  Репозиториев с коммитами в периоде: {len(stats.repos)}")

    print()
    print("=== Файлы (по списку файлов в коммитах) ===")
    print(f"  Всего записей файлов: {stats.files_touched:,}")
    for st in sorted(stats.files_by_status.keys()):
        print(f"    {st}: {stats.files_by_status[st]:,}")

    print()
    print("=== Пуши (публичные события, см. ограничение ~300 событий) ===")
    print(f"  Событий push:              {push_count}")
    print(f"  Коммитов в этих push-событиях: {commits_in_push_events}")

    if events_by_type:
        print()
        print("=== Прочая активность в ленте за период (тот же лимит ~300) ===")
        for et in sorted(events_by_type.keys(), key=lambda k: (-events_by_type[k], k)):
            if et == "PushEvent":
                continue
            print(f"  {et}: {events_by_type[et]}")

    print()
    print("=== Примечания ===")
    print("  • Поиск коммитов в основном по дефолтной ветке; форки могут быть неполными.")
    print("  • Потолок выдачи поиска ~1000 коммитов за запрос.")
    print("  • Пуши считаются только по последним публичным событиям профиля.")
    if not token:
        print("  • С токеном выше лимиты и видны приватные репозитории, доступные токену.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
