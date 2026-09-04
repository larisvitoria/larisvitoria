import os
import sys
import math
import datetime
import requests

TITLE_COLOR = "#FF1493"
ICON_COLOR = "#FF1493"
TEXT_COLOR = "#333333"
MUTED_COLOR = "#9B7385"
BORDER_COLOR = "#FFC4DA"
BG_COLOR = "#FFF5F8"
PINK_SHADES = [
    "#AD1457", "#D81B60", "#FF1493", "#FF4FA3", "#FF74B4",
    "#FF93C6", "#FFB0D4", "#FFC9E1", "#FFE0EE",
]

FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Helvetica, Arial, sans-serif"

GRAPHQL_URL = "https://api.github.com/graphql"


def run_query(query: str, variables: dict, token: str) -> dict:
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Erro na API do GitHub: {data['errors']}")
    return data["data"]


def get_account_created_at(username: str, token: str) -> datetime.date:
    query = """
    query($login: String!) {
      user(login: $login) { createdAt }
    }
    """
    data = run_query(query, {"login": username}, token)
    created = data["user"]["createdAt"]
    return datetime.date.fromisoformat(created[:10])


def get_followers_count(username: str, token: str) -> int:
    query = """
    query($login: String!) {
      user(login: $login) { followers { totalCount } }
    }
    """
    data = run_query(query, {"login": username}, token)
    return data["user"]["followers"]["totalCount"]


def get_contributions_all_time(username: str, token: str) -> dict:
    created = get_account_created_at(username, token)
    today = datetime.date.today()

    totals = {
        "commits": 0,
        "prs": 0,
        "issues": 0,
        "reviews": 0,
    }

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
        }
      }
    }
    """

    year_start = created
    while year_start <= today:
        year_end = min(
            datetime.date(year_start.year, 12, 31),
            today,
        )
        variables = {
            "login": username,
            "from": f"{year_start.isoformat()}T00:00:00Z",
            "to": f"{year_end.isoformat()}T23:59:59Z",
        }
        data = run_query(query, variables, token)
        c = data["user"]["contributionsCollection"]
        totals["commits"] += (
            c["totalCommitContributions"] + c["restrictedContributionsCount"]
        )
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        totals["reviews"] += c["totalPullRequestReviewContributions"]

        year_start = datetime.date(year_start.year + 1, 1, 1)

    return totals


def get_repos_stats(username: str, token: str) -> dict:
    query = """
    query($login: String!, $after: String) {
      user(login: $login) {
        repositories(first: 100, after: $after, ownerAffiliations: OWNER,
                      isFork: false, privacy: PUBLIC) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes {
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node { name color }
              }
            }
          }
        }
      }
    }
    """

    total_stars = 0
    repo_count = 0
    languages = {}
    cursor = None

    while True:
        data = run_query(
            query, {"login": username, "after": cursor}, token
        )
        repos = data["user"]["repositories"]
        for repo in repos["nodes"]:
            total_stars += repo["stargazerCount"]
            repo_count += 1
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                languages.setdefault(
                    name, {"size": 0, "color": edge["node"]["color"] or "#999999"}
                )
                languages[name]["size"] += edge["size"]

        if repos["pageInfo"]["hasNextPage"]:
            cursor = repos["pageInfo"]["endCursor"]
        else:
            break

    return {"stars": total_stars, "repos": repo_count, "languages": languages}


def calculate_rank(commits, prs, issues, reviews, stars, followers) -> str:
    def exp_cdf(x):
        return 1 - math.exp(-x)

    COMMITS_MEDIAN, COMMITS_WEIGHT = 250, 2
    PRS_MEDIAN, PRS_WEIGHT = 50, 3
    ISSUES_MEDIAN, ISSUES_WEIGHT = 25, 1
    REVIEWS_MEDIAN, REVIEWS_WEIGHT = 2, 1
    STARS_MEDIAN, STARS_WEIGHT = 50, 4
    FOLLOWERS_MEDIAN, FOLLOWERS_WEIGHT = 10, 1
    TOTAL_WEIGHT = (
        COMMITS_WEIGHT + PRS_WEIGHT + ISSUES_WEIGHT
        + REVIEWS_WEIGHT + STARS_WEIGHT + FOLLOWERS_WEIGHT
    )

    score = (
        COMMITS_WEIGHT * exp_cdf(commits / COMMITS_MEDIAN)
        + PRS_WEIGHT * exp_cdf(prs / PRS_MEDIAN)
        + ISSUES_WEIGHT * exp_cdf(issues / ISSUES_MEDIAN)
        + REVIEWS_WEIGHT * exp_cdf(reviews / REVIEWS_MEDIAN)
        + STARS_WEIGHT * exp_cdf(stars / STARS_MEDIAN)
        + FOLLOWERS_WEIGHT * exp_cdf(followers / FOLLOWERS_MEDIAN)
    ) / TOTAL_WEIGHT

    thresholds = [
        (0.90, "S+"), (0.80, "S"), (0.70, "S-"),
        (0.60, "A+"), (0.50, "A"), (0.40, "A-"),
        (0.30, "B+"), (0.20, "B"),
    ]
    for cutoff, label in thresholds:
        if score >= cutoff:
            return label
    return "C"


ICON_PATHS = {
    "star": (
        "M8 1.5 L9.8 5.6 L14.2 6 L10.9 8.9 L11.9 13.3 "
        "L8 11 L4.1 13.3 L5.1 8.9 L1.8 6 L6.2 5.6 Z"
    ),
    "commit": "M1.5 8 H5.3 M10.7 8 H14.5",
    "commit_circle": True,
    "pull_request": (
        "M4 3 V13 M4 3 C4 3 4 6 7 6 H10.5 "
        "M10.5 4 L12.5 6 L10.5 8"
    ),
    "pr_nodes": [(4, 3), (4, 13), (12.5, 6)],
    "issue": "M8 4.8 V8.6 M8 11 V11.05",
    "issue_circle": True,
    "eye": "M1.5 8 C3.5 4.5 12.5 4.5 14.5 8 C12.5 11.5 3.5 11.5 1.5 8 Z",
    "eye_pupil": True,
    "package": (
        "M8 1.8 L14 4.8 V11.2 L8 14.2 L2 11.2 V4.8 Z "
        "M2 4.8 L8 7.8 L14 4.8 M8 7.8 V14.2"
    ),
}


def render_icon(kind: str, cx: float, cy: float) -> str:
    size = 20
    x, y = cx - size / 2, cy - size / 2
    inner = f'<g transform="translate({x + 2}, {y + 2})">'

    if kind == "star":
        inner += f'<path d="{ICON_PATHS["star"]}" fill="white" stroke="none"/>'
    elif kind == "commit":
        inner += (
            f'<path d="{ICON_PATHS["commit"]}" stroke="white" '
            f'stroke-width="1.6" stroke-linecap="round" fill="none"/>'
            f'<circle cx="8" cy="8" r="2.3" fill="none" stroke="white" stroke-width="1.6"/>'
        )
    elif kind == "pull_request":
        inner += (
            f'<path d="{ICON_PATHS["pull_request"]}" stroke="white" '
            f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
            f'<circle cx="4" cy="3" r="1.6" fill="white"/>'
            f'<circle cx="4" cy="13" r="1.6" fill="white"/>'
            f'<circle cx="10.5" cy="4" r="1.3" fill="white"/>'
        )
    elif kind == "issue":
        inner += (
            f'<circle cx="8" cy="8" r="6.3" fill="none" stroke="white" stroke-width="1.5"/>'
            f'<path d="{ICON_PATHS["issue"]}" stroke="white" stroke-width="1.6" '
            f'stroke-linecap="round" fill="none"/>'
        )
    elif kind == "eye":
        inner += (
            f'<path d="{ICON_PATHS["eye"]}" fill="none" stroke="white" '
            f'stroke-width="1.5" stroke-linejoin="round"/>'
            f'<circle cx="8" cy="8" r="1.8" fill="white"/>'
        )
    elif kind == "package":
        inner += (
            f'<path d="{ICON_PATHS["package"]}" fill="none" stroke="white" '
            f'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
        )

    inner += "</g>"

    return f"""
        <circle cx="{cx}" cy="{cy}" r="{size / 2}" fill="{ICON_COLOR}"/>
        {inner}"""


def render_stats_svg(stats: dict) -> str:
    rows = [
        ("star", "Estrelas ganhas", stats["stars"]),
        ("commit", "Commits", stats["commits"]),
        ("pull_request", "Pull Requests", stats["prs"]),
        ("issue", "Issues", stats["issues"]),
        ("package", "Repositórios", stats["repos"]),
    ]

    width, height = 450, 215
    line_height = 24
    start_y = 82
    body = ""
    for i, (icon, label, value) in enumerate(rows):
        y = start_y + i * line_height
        body += f"""
        <g transform="translate(30, {y})">
          {render_icon(icon, 12, -5)}
          <text x="34" fill="{TEXT_COLOR}" font-size="14">{label}</text>
          <text x="270" text-anchor="end" fill="{TEXT_COLOR}"
                font-size="14" font-weight="600">{value}</text>
        </g>"""

    rank = stats["rank"]

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
     xmlns="http://www.w3.org/2000/svg" font-family="{FONT}" role="img"
     aria-label="Estatísticas do GitHub">
  <defs>
    <filter id="cardShadow" x="-8%" y="-8%" width="116%" height="120%">
      <feDropShadow dx="0" dy="2" stdDeviation="4"
                    flood-color="{TITLE_COLOR}" flood-opacity="0.15"/>
    </filter>
  </defs>
  <rect x="1" y="1" rx="14" width="{width - 2}" height="{height - 2}"
        fill="{BG_COLOR}" stroke="{BORDER_COLOR}" stroke-width="1"
        filter="url(#cardShadow)"/>
  <text x="30" y="42" font-size="19" font-weight="700"
        fill="{TITLE_COLOR}">Estatísticas do GitHub</text>
  <line x1="30" y1="56" x2="300" y2="56"
        stroke="{BORDER_COLOR}" stroke-width="1.5"/>
  {body}
  <g transform="translate(378, 132)">
    <circle r="35" fill="none" stroke="{ICON_COLOR}" stroke-width="6"
            opacity="0.18"/>
    <circle r="35" fill="none" stroke="{ICON_COLOR}" stroke-width="6"
            stroke-linecap="round"
            stroke-dasharray="220" stroke-dashoffset="55"
            transform="rotate(-90)"/>
    <text text-anchor="middle" dy="7" font-size="22" font-weight="700"
          fill="{TITLE_COLOR}">{rank}</text>
  </g>
</svg>"""


def render_langs_svg(languages: dict, top_n: int = 9) -> str:
    width, height = 450, 215
    total_size = sum(v["size"] for v in languages.values()) or 1
    top = sorted(languages.items(), key=lambda kv: kv[1]["size"], reverse=True)[:top_n]

    bar_x0 = 30
    bar_y = 58
    bar_width = width - 60
    bar_h = 10

    segments = ""
    seg_x = bar_x0
    for i, (name, info) in enumerate(top): 
        color = PINK_SHADES[i % len(PINK_SHADES)]
        pct = info["size"] / total_size
        seg_width = bar_width * pct
        segments += (
            f'<rect x="{seg_x:.2f}" y="{bar_y}" width="{seg_width:.2f}" '
            f'height="{bar_h}" fill="{color}"/>'
        )
        seg_x += seg_width

    col_width = (width - 60) / 2
    row_height = 26
    grid_start_y = 92
    rows = ""
    for i, (name, info) in enumerate(top):
        color = PINK_SHADES[i % len(PINK_SHADES)]
        pct = 100 * info["size"] / total_size
        col = i % 2
        row = i // 2
        gx = bar_x0 + col * col_width
        gy = grid_start_y + row * row_height
        rows += f"""
        <g transform="translate({gx:.1f}, {gy})">
          <circle cx="6" cy="-4" r="6" fill="{color}"/> 
          <text x="20" fill="{TEXT_COLOR}" font-size="13">{name}</text>
          <text x="{col_width - 12:.1f}" text-anchor="end" fill="{MUTED_COLOR}"
                font-size="12.5">{pct:.1f}%</text>
        </g>"""

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
     xmlns="http://www.w3.org/2000/svg" font-family="{FONT}" role="img"
     aria-label="Linguagens mais usadas">
  <defs>
    <filter id="langShadow" x="-8%" y="-8%" width="116%" height="120%">
      <feDropShadow dx="0" dy="2" stdDeviation="4"
                    flood-color="{TITLE_COLOR}" flood-opacity="0.15"/>
    </filter>
    <clipPath id="barClip">
      <rect x="{bar_x0}" y="{bar_y}" width="{bar_width}" height="{bar_h}"
            rx="{bar_h / 2}"/>
    </clipPath>
  </defs>
  <rect x="1" y="1" rx="14" width="{width - 2}" height="{height - 2}"
        fill="{BG_COLOR}" stroke="{BORDER_COLOR}" stroke-width="1"
        filter="url(#langShadow)"/>
  <text x="30" y="42" font-size="19" font-weight="700"
        fill="{TITLE_COLOR}">Tecnologias</text>
  <g clip-path="url(#barClip)">
    <rect x="{bar_x0}" y="{bar_y}" width="{bar_width}" height="{bar_h}"
          fill="#F0D8E2"/>
    {segments}
  </g>
  {rows}
</svg>"""


def main():
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("GITHUB_USERNAME")

    if not token or not username:
        print("Defina GITHUB_TOKEN e GITHUB_USERNAME.", file=sys.stderr)
        sys.exit(1)

    print(f"Coletando dados de {username}...")

    contrib = get_contributions_all_time(username, token)
    repo_stats = get_repos_stats(username, token)
    followers = get_followers_count(username, token)

    rank = calculate_rank(
        commits=contrib["commits"],
        prs=contrib["prs"],
        issues=contrib["issues"],
        reviews=contrib["reviews"],
        stars=repo_stats["stars"],
        followers=followers,
    )

    stats = {
        "commits": contrib["commits"],
        "prs": contrib["prs"],
        "issues": contrib["issues"],
        "reviews": contrib["reviews"],
        "stars": repo_stats["stars"],
        "repos": repo_stats["repos"],
        "rank": rank,
    }

    out_dir = "assets"
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(render_stats_svg(stats))

    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(render_langs_svg(repo_stats["languages"]))

    print("SVGs gerados em assets/stats.svg e assets/top-langs.svg")


if __name__ == "__main__":
    main()