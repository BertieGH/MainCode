"""LinkedIn links a company publishes on its own site. No network.

The leadership markup is BlueWave's, as its page serves it: a bio, then an
icon link titled "LinkedIn" with no name in it.
"""

from __future__ import annotations

import pytest

from app.services import site_links
from app.services.site_links import Profile

LEADERSHIP = """
<div class="team-member"><h3>Seth Penland</h3><p>Seth holds a BS in Applied Economics.</p>
  <div class="team-social"><a title="LinkedIn" target="_blank" href="https://www.linkedin.com/in/seth-penland/"><span class="icon-linkedin"></span></a></div></div>
<div class="team-member"><h3>Kevin Burke</h3><p>Kevin is a licensed CPA (retired).</p>
  <div class="team-social"><a title="LinkedIn" target="_blank" href="https://www.linkedin.com/in/kevin-burke-a28a302/"><span class="icon-linkedin"></span></a></div></div>
<div class="team-member"><h3>Marcus Chen</h3><p>Marcus leads client advisory.</p>
  <div class="team-social"><a href="https://www.linkedin.com/in/mchen-advisory/" aria-label="Marcus Chen on LinkedIn"></a></div></div>
"""

HOME = '<footer><a href="https://www.linkedin.com/company/meridian-cloud/">in</a></footer>'


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class FakeClient:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.asked = pages, set(fail), []

    async def get(self, url):
        self.asked.append(url)
        if url in self.fail:
            raise ConnectionError("timed out")
        return FakeResponse(200, self.pages[url]) if url in self.pages else FakeResponse(404, "")

    async def aclose(self):
        return None


class TestReadingProfileLinks:
    def test_icon_links_are_read_by_their_address(self):
        found = site_links.profiles_in(LEADERSHIP)
        assert [p.url for p in found] == [
            "https://www.linkedin.com/in/seth-penland",
            "https://www.linkedin.com/in/kevin-burke-a28a302",
            "https://www.linkedin.com/in/mchen-advisory",
        ]
        assert found[0].label == "", "a bare 'LinkedIn' title names nobody"
        assert found[2].label == "Marcus Chen on LinkedIn"


class TestWhoseProfileItIs:
    PROFILES = site_links.profiles_in(LEADERSHIP)

    @pytest.mark.parametrize(
        ("name", "url"),
        [
            ("Seth Penland", "https://www.linkedin.com/in/seth-penland"),
            ("Kevin Burke", "https://www.linkedin.com/in/kevin-burke-a28a302"),
            # Not in the address, but the link names him.
            ("Marcus Chen", "https://www.linkedin.com/in/mchen-advisory"),
        ],
    )
    def test_a_person_is_matched_by_address_or_by_the_links_own_words(self, name, url):
        assert site_links.profile_for(name, self.PROFILES) == url

    def test_someone_not_on_the_page_matches_nothing(self):
        assert site_links.profile_for("Rachel Adams", self.PROFILES) is None

    def test_the_name_beside_a_link_is_not_enough(self):
        """Seth's name is in the heading above his icon — and a team grid puts
        the previous person's name above the next icon just as readily."""
        bare = [Profile("https://www.linkedin.com/in/sp-8812", "")]
        assert site_links.profile_for("Seth Penland", bare) is None

    def test_two_matching_profiles_are_not_guessed_between(self):
        twins = [
            Profile("https://www.linkedin.com/in/dana-reyes", ""),
            Profile("https://www.linkedin.com/in/dana-reyes-7731", ""),
        ]
        assert site_links.profile_for("Dana Reyes", twins) is None

    def test_accents_and_hyphens_fold(self):
        profiles = [Profile("https://www.linkedin.com/in/sophia-almansoor", "")]
        assert site_links.profile_for("Sophia Al-Mansoor", profiles) == profiles[0].url

    @pytest.mark.parametrize("name", ["Cher", "J Li", ""])
    def test_a_single_name_or_initials_are_too_little(self, name):
        assert site_links.profile_for(name, [Profile("https://www.linkedin.com/in/cher-j-li", "Cher J Li")]) is None


class TestReadingASite:
    async def test_company_page_and_profiles_across_pages(self):
        http = FakeClient({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/leadership": LEADERSHIP,
        })
        links = await site_links.read_site("meridiancloud.io", http=http)
        assert links.answered and links.pages_read == 2
        assert site_links.company_page(links) == "https://linkedin.com/company/meridian-cloud"
        assert len(links.profiles) == 3

    async def test_two_company_pages_are_not_guessed_between(self):
        home = HOME + '<a href="https://www.linkedin.com/company/meridian-labs">labs</a>'
        links = await site_links.read_site("meridiancloud.io", http=FakeClient({"https://meridiancloud.io/": home}))
        assert site_links.company_page(links) is None
        assert len(links.company_pages) == 2

    async def test_a_site_that_does_not_answer_is_asked_once(self):
        http = FakeClient({}, fail={"https://gone.example/robots.txt"})
        links = await site_links.read_site("gone.example", http=http)
        assert links.answered is False
        assert http.asked == ["https://gone.example/robots.txt"]

    async def test_robots_is_honoured(self):
        http = FakeClient({
            "https://meridiancloud.io/robots.txt": "User-agent: *\nDisallow: /leadership\n",
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/leadership": LEADERSHIP,
        })
        links = await site_links.read_site("meridiancloud.io", http=http)
        assert "https://meridiancloud.io/leadership" not in http.asked
        assert links.profiles == []
