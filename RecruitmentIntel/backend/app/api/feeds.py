from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.feed_source import FeedSource
from app.schemas.feed import FeedCreate, FeedUpdate, FeedOut

router = APIRouter()


# Curated set of public funding-news feeds the user can bulk-add to get
# something flowing without hunting for URLs themselves.
SUGGESTED_FEEDS = [
    {
        "name": "Crunchbase News",
        "url": "https://news.crunchbase.com/feed/",
        "feed_type": "Crunchbase",
        "keywords": ["funding", "raised", "series"],
    },
    {
        "name": "TechCrunch — Venture",
        "url": "https://techcrunch.com/category/venture/feed/",
        "feed_type": "Custom",
        "keywords": ["funding", "raised", "series"],
    },
    {
        "name": "TechCrunch — Startups",
        "url": "https://techcrunch.com/category/startups/feed/",
        "feed_type": "Custom",
        "keywords": ["funding", "raised", "series"],
    },
    {
        "name": "VentureBeat",
        "url": "https://venturebeat.com/feed/",
        "feed_type": "Custom",
        "keywords": ["funding", "raised", "series"],
    },
    {
        "name": "Google News — Series A funding",
        "url": "https://news.google.com/rss/search?q=%22series+a%22+funding+raised&hl=en-US&gl=US&ceid=US:en",
        "feed_type": "Google News",
        "keywords": ["series a", "raised"],
    },
    {
        "name": "Google News — Seed round",
        "url": "https://news.google.com/rss/search?q=%22seed+round%22+raised+startup&hl=en-US&gl=US&ceid=US:en",
        "feed_type": "Google News",
        "keywords": ["seed", "raised"],
    },
    {
        "name": "Google News — Series B funding",
        "url": "https://news.google.com/rss/search?q=%22series+b%22+funding+raised&hl=en-US&gl=US&ceid=US:en",
        "feed_type": "Google News",
        "keywords": ["series b", "raised"],
    },
]


@router.get("/feeds", response_model=list[FeedOut])
async def list_feeds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeedSource).order_by(FeedSource.created_at.desc()))
    return result.scalars().all()


@router.post("/feeds", response_model=FeedOut)
async def create_feed(data: FeedCreate, db: AsyncSession = Depends(get_db)):
    feed = FeedSource(
        name=data.name,
        url=data.url,
        feed_type=data.feed_type,
        keywords=data.keywords,
    )
    db.add(feed)
    await db.commit()
    await db.refresh(feed)
    return feed


@router.get("/feeds/{feed_id}", response_model=FeedOut)
async def get_feed(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeedSource).where(FeedSource.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


@router.put("/feeds/{feed_id}", response_model=FeedOut)
async def update_feed(feed_id: UUID, data: FeedUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeedSource).where(FeedSource.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(feed, field, value)

    await db.commit()
    await db.refresh(feed)
    return feed


@router.delete("/feeds/{feed_id}")
async def delete_feed(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeedSource).where(FeedSource.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    await db.delete(feed)
    await db.commit()
    return {"status": "deleted"}


@router.get("/feeds/suggested/list")
async def list_suggested_feeds(db: AsyncSession = Depends(get_db)):
    """Return curated feeds, marking which are already added so the UI can dim them."""
    existing = await db.execute(select(FeedSource.url))
    existing_urls = {row[0] for row in existing.fetchall()}
    return [
        {**preset, "already_added": preset["url"] in existing_urls}
        for preset in SUGGESTED_FEEDS
    ]


@router.post("/feeds/suggested/add-all", response_model=list[FeedOut])
async def add_all_suggested_feeds(db: AsyncSession = Depends(get_db)):
    """Bulk-add every suggested feed that isn't already present (by URL)."""
    existing = await db.execute(select(FeedSource.url))
    existing_urls = {row[0] for row in existing.fetchall()}

    created = []
    for preset in SUGGESTED_FEEDS:
        if preset["url"] in existing_urls:
            continue
        feed = FeedSource(
            name=preset["name"],
            url=preset["url"],
            feed_type=preset["feed_type"],
            keywords=preset["keywords"],
        )
        db.add(feed)
        created.append(feed)

    await db.commit()
    for f in created:
        await db.refresh(f)
    return created
