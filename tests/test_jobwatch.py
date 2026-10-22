import time
import unittest
from unittest import mock

from jobwatch import main, slack
from jobwatch.sources import Source
from jobwatch.state import State

NOW = time.time()
SRC = Source("intern", "Summer 2027 Internship", "SimplifyJobs/Summer2027-Internships")


def listing(id, active=True, visible=True, age=60):
    return {
        "id": id,
        "company_name": f"Co{id}",
        "title": "SWE Intern",
        "url": f"https://example.com/{id}",
        "locations": ["SF", "NYC"],
        "category": "Software",
        "terms": ["Summer 2027"],
        "active": active,
        "is_visible": visible,
        "date_posted": int(NOW - age),
    }


class FindNewTest(unittest.TestCase):
    def test_filters_seen_inactive_hidden_and_old(self):
        listings = [
            listing("a"),
            listing("seen"),
            listing("inactive", active=False),
            listing("hidden", visible=False),
            listing("old", age=main.MAX_AGE_SECONDS + 10),
        ]
        new = main.find_new(listings, {"seen"}, NOW)
        self.assertEqual([l["id"] for l in new], ["a"])

    def test_sorted_oldest_first(self):
        new = main.find_new([listing("b", age=10), listing("a", age=100)], set(), NOW)
        self.assertEqual([l["id"] for l in new], ["a", "b"])


class CheckSourceTest(unittest.TestCase):
    def setUp(self):
        self.state = State(":memory:")
        patcher = mock.patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example/x"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_check(self, listings, etag="e1"):
        with mock.patch.object(main, "fetch_listings", return_value=(listings, etag)), \
             mock.patch.object(main.slack, "post") as post, \
             mock.patch.object(main.time, "sleep"):
            main.check_source(SRC, self.state, dry_run=False)
        return post

    def test_first_run_seeds_without_posting(self):
        post = self.run_check([listing("a"), listing("b")])
        post.assert_not_called()
        self.assertEqual(self.state.seen_ids("intern"), {"a", "b"})
        self.assertEqual(self.state.get_etag("intern"), "e1")

    def test_posts_only_new_and_marks_all_seen(self):
        self.run_check([listing("a")])
        post = self.run_check([listing("a"), listing("b"), listing("c", active=False)], etag="e2")
        self.assertEqual(post.call_count, 1)
        self.assertIn("Cob", post.call_args[0][1]["text"])
        self.assertEqual(self.state.seen_ids("intern"), {"a", "b", "c"})
        self.assertEqual(self.state.get_etag("intern"), "e2")

    def test_unchanged_does_nothing(self):
        self.run_check([listing("a")])
        post = self.run_check(None)
        post.assert_not_called()

    def test_failed_post_is_retried_next_cycle(self):
        self.run_check([listing("a")])
        with mock.patch.object(main, "fetch_listings", return_value=([listing("a"), listing("b")], "e2")), \
             mock.patch.object(main.slack, "post", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                main.check_source(SRC, self.state, dry_run=False)
        self.assertNotIn("b", self.state.seen_ids("intern"))
        self.assertEqual(self.state.get_etag("intern"), "e1")


class BuildMessageTest(unittest.TestCase):
    def test_message_contents(self):
        l = listing("x")
        l["locations"] = ["A", "B", "C", "D", "E", "F"]
        msg = slack.build_message(l, "New Grad")
        self.assertEqual(msg["text"], "New Grad: Cox — SWE Intern")
        flat = str(msg["blocks"])
        self.assertIn("+2 more", flat)
        self.assertIn("https://example.com/x", flat)


if __name__ == "__main__":
    unittest.main()
