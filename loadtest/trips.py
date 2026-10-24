"""Trips used by the load test, with the expected outcome of each (default strategy, full tank).

Expected costs come from a baseline run and let Locust verify *correctness* under load,
not just status codes: a race in a cache or the lazy index would surface as a wrong total.
"""

TRIPS = [
    # (start, finish, expected_status, expected_total_fuel_cost or None)
    ("New York, NY", "Los Angeles, CA", 200, 705.57),
    ("Buffalo, NY", "San Diego, CA", 200, 642.89),
    ("Chicago, IL", "Denver, CO", 200, 141.50),
    ("Houston, TX", "Atlanta, GA", 200, 84.90),
    ("Miami, FL", "Seattle, WA", 200, 852.59),
    ("Boston, MA", "Miami, FL", 200, 293.14),
    ("Dallas, TX", "Chicago, IL", 200, 133.23),
    ("Phoenix, AZ", "Nashville, TN", 200, 340.94),
    ("Salt Lake City, UT", "New Orleans, LA", 200, 360.91),
    ("Seattle, WA", "Minneapolis, MN", 200, 387.90),
    ("Detroit, MI", "Kansas City, MO", 200, 79.44),
    ("Los Angeles, CA", "New York, NY", 200, 705.78),
    ("Los Angeles, CA", "Seattle, WA", 422, None),
]
