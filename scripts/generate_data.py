#!/usr/bin/env python
"""Generate a *realistic* synthetic employee master CSV.

    python scripts/generate_data.py -n 200000 --seed 42

Real HR data isn't uniform, so neither is this. The structure baked in:
  * Department sizes vary (Engineering large, Legal small).
  * Designations form a pyramid (many Associates, few VPs).
  * Salary tracks seniority x department, with a right-skewed noise term.
  * Age tracks seniority (interns young, directors older).
  * Hiring grows toward recent years; senior staff have longer tenure.
  * Ratings cluster around 3-4 rather than spreading flat across 1-5.
  * Attrition (Inactive) rises with tenure; gender mix skews by department.

Vectorized with numpy, so 200k rows generate in a couple of seconds.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from faker import Faker  # noqa: E402

from employee_service import config  # noqa: E402

# --- categorical worlds + weights (weights need not sum to 1; normalized later)
DEPARTMENTS = {
    "Engineering": 24, "Sales": 15, "Operations": 12, "Customer Support": 11,
    "Product": 8, "Marketing": 8, "Finance": 7, "IT": 6,
    "Human Resources": 5, "Legal": 4,
}
DESIGNATIONS = {
    "Intern": 6, "Associate": 30, "Senior Associate": 24, "Team Lead": 14,
    "Manager": 12, "Senior Manager": 8, "Director": 4, "VP": 2,
}
LOCATIONS = {
    "Bengaluru": 28, "Hyderabad": 16, "Pune": 12, "Chennai": 10, "Gurugram": 9,
    "Mumbai": 8, "Noida": 6, "Delhi": 5, "Kolkata": 3, "Ahmedabad": 3,
}

LEVEL = {d: i for i, d in enumerate(DESIGNATIONS)}           # 0..7 seniority
BASE_SALARY = {  # INR annual base by designation, before dept factor + noise
    "Intern": 400_000, "Associate": 800_000, "Senior Associate": 1_400_000,
    "Team Lead": 2_200_000, "Manager": 3_200_000, "Senior Manager": 4_500_000,
    "Director": 7_000_000, "VP": 11_000_000,
}
DEPT_PAY_FACTOR = {
    "Engineering": 1.15, "Product": 1.20, "Finance": 1.10, "Legal": 1.12,
    "IT": 1.05, "Sales": 1.05, "Marketing": 0.95, "Operations": 0.88,
    "Customer Support": 0.80, "Human Resources": 0.90,
}
AGE_CENTER = {  # mean age by designation; individual ages vary around it
    "Intern": 22, "Associate": 26, "Senior Associate": 30, "Team Lead": 34,
    "Manager": 38, "Senior Manager": 43, "Director": 48, "VP": 52,
}
# Gender mix skews by department (makes cross-filtering reveal real patterns).
DEPT_GENDER = {  # [P(Male), P(Female), P(Other)]
    "Engineering": [0.70, 0.28, 0.02], "IT": [0.68, 0.30, 0.02],
    "Product": [0.60, 0.38, 0.02], "Sales": [0.58, 0.40, 0.02],
    "Operations": [0.55, 0.43, 0.02], "Finance": [0.52, 0.46, 0.02],
    "Legal": [0.48, 0.50, 0.02], "Marketing": [0.45, 0.53, 0.02],
    "Customer Support": [0.45, 0.53, 0.02], "Human Resources": [0.35, 0.63, 0.02],
}
RATING_P = [0.05, 0.13, 0.42, 0.30, 0.10]  # over ratings 1..5 -> mean ~3.27


def _weighted(rng, mapping: dict, n: int) -> np.ndarray:
    keys = list(mapping)
    p = np.array(list(mapping.values()), dtype=float)
    return rng.choice(keys, size=n, p=p / p.sum())


def _per_row_choice(rng, choices, prob_rows: np.ndarray) -> np.ndarray:
    """Sample one of `choices` per row, where prob_rows[i] is that row's dist."""
    cdf = np.cumsum(prob_rows, axis=1)
    u = rng.random(len(prob_rows))[:, None]
    idx = (u > cdf).sum(axis=1).clip(0, len(choices) - 1)
    return np.asarray(choices)[idx]


def build(n: int, seed: int, start_id: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fake = Faker("en_IN")
    Faker.seed(seed)

    # Name pools sampled by index (calling Faker n times would be slow).
    first_pool = np.array([fake.first_name() for _ in range(4000)])
    last_pool = np.array([fake.last_name() for _ in range(4000)])
    first = first_pool[rng.integers(0, len(first_pool), n)]
    last = last_pool[rng.integers(0, len(last_pool), n)]
    managers = np.array([f"{fake.first_name()} {fake.last_name()}" for _ in range(300)])

    department = _weighted(rng, DEPARTMENTS, n)
    designation = _weighted(rng, DESIGNATIONS, n)
    location = _weighted(rng, LOCATIONS, n)

    level = pd.Series(designation).map(LEVEL).to_numpy()

    # Salary = base(designation) x dept factor x right-skewed noise, floored.
    base = pd.Series(designation).map(BASE_SALARY).to_numpy()
    factor = pd.Series(department).map(DEPT_PAY_FACTOR).to_numpy()
    noise = rng.lognormal(mean=0.0, sigma=0.18, size=n)
    salary = np.clip(np.round(base * factor * noise, -3), 300_000, None)

    # Age centered on seniority, with spread.
    age = np.clip(
        np.round(rng.normal(pd.Series(designation).map(AGE_CENTER).to_numpy(), 3.5)),
        21, 62,
    ).astype(int)

    # Tenure: exponential (many recent hires) + seniority shift (seniors longer).
    tenure_days = np.clip(
        rng.exponential(scale=950, size=n) + level * 280, 30, 18 * 365
    )
    doj = (pd.Timestamp.today().normalize()
           - pd.to_timedelta(tenure_days, unit="D")).normalize()

    # Interns are Interns; everyone else Full-time (mostly) or Contract.
    is_intern = designation == "Intern"
    non_intern_type = rng.choice(["Full-time", "Contract"], size=n, p=[0.88, 0.12])
    employment_type = np.where(is_intern, "Intern", non_intern_type)

    # Attrition rises with tenure.
    p_inactive = np.clip(0.04 + (tenure_days / (18 * 365)) * 0.28, 0.04, 0.35)
    status = np.where(rng.random(n) < p_inactive, "Inactive", "Active")

    gender = _per_row_choice(
        rng, ["Male", "Female", "Other"],
        np.array([DEPT_GENDER[d] for d in department]),
    )
    rating = rng.choice([1, 2, 3, 4, 5], size=n, p=RATING_P)

    # Start emp_ids / email indices at `start_id` so a batch can be appended to an
    # existing table without colliding on the unique emp_id / email constraints.
    idx = np.arange(start_id, start_id + n)
    return pd.DataFrame({
        "emp_id": [f"EMP{i:06d}" for i in idx],
        "full_name": np.char.add(np.char.add(first, " "), last),
        "email": [f"{f}.{l}{i}@example.com".lower().replace(" ", "")
                  for f, l, i in zip(first, last, idx)],
        "department": department,
        "designation": designation,
        "employment_type": employment_type,
        "status": status,
        "location": location,
        "gender": gender,
        "date_of_joining": doj.strftime("%Y-%m-%d"),
        "age": age,
        "salary": salary,
        "performance_rating": rating,
        "manager_name": managers[rng.integers(0, len(managers), n)],
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate realistic synthetic employee CSV.")
    ap.add_argument("-n", "--rows", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start-id", default="1",
                    help="First emp_id number (e.g. 200001 to append past an "
                         "existing table). Use 'auto' to continue after the "
                         "current max emp_id in the database (reads DATABASE_URL).")
    ap.add_argument("-o", "--output", default=str(config.MASTER_CSV))
    args = ap.parse_args()

    if str(args.start_id).lower() == "auto":
        # Look up the next free emp_id from whatever DB DATABASE_URL points at.
        from employee_service import repository as repo
        from employee_service.database import session_scope
        with session_scope() as s:
            start_id = repo.next_emp_id_number(s)
        print(f"Auto start-id: continuing at EMP{start_id:06d} "
              f"({config.DATABASE_URL})")
    else:
        start_id = int(args.start_id)

    df = build(args.rows, args.seed, start_id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df):,} rows -> {out}")


if __name__ == "__main__":
    main()
