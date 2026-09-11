import pytest
from google_books_client import _parse_known_title_entry


@pytest.mark.parametrize(
    "input_entry, expected_title, expected_author",
    [
        # Standard "by" pattern
        ("The Sun and Her Flowers by Rupi Kaur", "The Sun and Her Flowers", "Rupi Kaur"),
        ("Klara and the Sun by Kazuo Ishiguro", "Klara and the Sun", "Kazuo Ishiguro"),
        ("  'Milk and Honey by Rupi Kaur'  ", "Milk and Honey", "Rupi Kaur"),

        # Multiple "by" occurrences
        ("Driven by Data by John Doe", "Driven by Data", "John Doe"),
        ("Side by Side by Sandra Boynton", "Side by Side", "Sandra Boynton"),
        ("By the Sea by Jane Austen", "By the Sea", "Jane Austen"),

        # Possessives ("Author's Title" & curly apostrophe)
        ("Rupi Kaur's The Sun and Her Flowers", "The Sun and Her Flowers", "Rupi Kaur"),
        ("Kazuo Ishiguro’s Klara and the Sun", "Klara and the Sun", "Kazuo Ishiguro"),
        ("Mary Oliver's Devotions", "Devotions", "Mary Oliver"),

        # Hyphens and En-dashes
        ("The Sun and Her Flowers - Rupi Kaur", "The Sun and Her Flowers", "Rupi Kaur"),
        ("Devotions – Mary Oliver", "Devotions", "Mary Oliver"),

        # Fallbacks (no author pattern matched)
        ("Just A Title", "Just A Title", None),
    ],
)
def test_parse_known_title_entry(input_entry, expected_title, expected_author):
    title, author = _parse_known_title_entry(input_entry)
    assert title == expected_title
    assert author == expected_author
