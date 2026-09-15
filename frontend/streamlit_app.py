"""
Book-Buddy-AI Streamlit App
Multi-page app with login and recommendations
"""

import streamlit as st
from api_client import get_recommendations, submit_feedback, BackendError, DEMO_MODE

# Custom CSS for styling
st.markdown("""
<style>
    /* Make metrics smaller */
    [data-testid="stMetricContainer"] {
        padding: 0.5rem 0;
    }
    [data-testid="stMetricContainer"] > div:first-child {
        font-size: 0.75rem;
    }
    [data-testid="stMetricContainer"] > div:last-child {
        font-size: 1.2rem;
    }

    /* Reduce gap between title and description */
    .element-container:has(+ .element-container) {
        margin-bottom: 0rem !important;
    }
    [data-testid="stCaptionContainer"] {
        margin-top: -0.8rem !important;
        margin-bottom: 0.5rem !important;
    }


    /* Light mustard yellow for Logout and Submit buttons only */
    /* Target buttons in specific columns by position */
    .stColumns > div:nth-last-child(2) button,
    .stColumns:last-of-type > div:first-child button {
        background-color: #F4D03F !important;
        color: #333 !important;
    }
    .stColumns > div:nth-last-child(2) button:hover,
    .stColumns:last-of-type > div:first-child button:hover {
        background-color: #E8C41F !important;
    }
</style>
""", unsafe_allow_html=True)

# Page configuration
st.set_page_config(
    page_title="Book-Buddy-AI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state
if "user_email" not in st.session_state:
    st.session_state.user_email = None

if "current_books" not in st.session_state:
    st.session_state.current_books = []

if "liked_votes" not in st.session_state:
    st.session_state.liked_votes = set()

if "rejected_votes" not in st.session_state:
    st.session_state.rejected_votes = set()

if "feedback_submitted" not in st.session_state:
    st.session_state.feedback_submitted = False


def login_page():
    """Login/welcome page to collect user email."""
    st.markdown("# 📚 Book-Buddy-AI")
    st.markdown("## Get personalized book recommendations")

    left_spacer, center_col, right_spacer = st.columns([1, 2, 1])

    with center_col:
        st.markdown("---")
        st.markdown("### Enter your email to get started")

        email = st.text_input(
            "Email address",
            placeholder="your@email.com",
            help="We'll use this for personalized recommendations"
        )

        if st.button("Continue", use_container_width=True, type="primary"):
            if email and "@" in email:
                st.session_state.user_email = email
                st.success(f"Welcome! 👋")
                st.rerun()
            else:
                st.error("Please enter a valid email address")

        st.markdown("---")
        st.info("💡 Demo mode active - instant recommendations without backend calls" if DEMO_MODE else "ℹ️ Connected to backend")


def recommendations_page():
    """Main recommendations page with vote buttons."""
    st.markdown("# 📚 Book-Buddy-AI")

    # User info and logout
    user_info_col, logout_col = st.columns([3, 0.33])
    with user_info_col:
        st.markdown(f"**User:** {st.session_state.user_email}")
    with logout_col:
        if st.button("Logout", key="logout", use_container_width=True):
            st.session_state.user_email = None
            st.session_state.current_books = []
            st.session_state.liked_votes = set()
            st.session_state.rejected_votes = set()
            st.rerun()

    st.markdown("---")

    # Query input
    st.markdown("### What would you like to read about?")
    st.caption("For example: \"My son loves cars. Suggest some books.\" or \"I'd like to learn about spirituality.\"")

    query = st.text_area(
        "Your reading interest",
        placeholder="Describe what kind of books you're looking for...",
        key="query_input",
        height=80,
        label_visibility="collapsed"
    )

    # Small button for getting recommendations
    button_col, spacer_col = st.columns([0.2, 0.8])
    with button_col:
        if st.button("Get Recommendations", type="primary", use_container_width=True):
            if query:
                with st.spinner("🔍 Finding recommendations..."):
                    try:
                        response = get_recommendations(query)
                        books = []

                        if response.get("request_type") == "progression":
                            for level in response.get("levels", []):
                                for rec in level.get("recommendations", []):
                                    books.append({
                                        "title": rec.get("title", "Unknown"),
                                        "authors": ", ".join(rec.get("authors", [])),
                                        "description": rec.get("why_recommended", "")
                                    })
                        else:
                            for rec in response.get("recommendations", []):
                                books.append({
                                    "title": rec.get("title", "Unknown"),
                                    "authors": ", ".join(rec.get("authors", [])),
                                    "description": rec.get("why_recommended", "")
                                })

                        st.session_state.current_books = books
                        st.session_state.liked_votes = set()
                        st.session_state.rejected_votes = set()
                        st.success(f"✨ Found {len(books)} recommendations!")

                    except BackendError as e:
                        st.error(f"Error: {str(e)}")
            else:
                st.warning("Please enter what you'd like to read about")

    st.markdown("---")

    # Display recommendations with vote buttons
    if st.session_state.current_books:
        st.markdown("### Rate these recommendations")
        st.markdown("Click 👍 to like or 👎 to reject")
        st.caption("💡 If you'd like to avoid a particular book or author in future recommendations, select the 👎 button and submit your feedback — we will remove it from your future recommendations.")

        for i, book in enumerate(st.session_state.current_books, 1):
            book_title = book["title"] if isinstance(book, dict) else book
            book_authors = book.get("authors", "") if isinstance(book, dict) else ""
            book_description = book.get("description", "") if isinstance(book, dict) else ""

            like_col, reject_col, book_col = st.columns([0.6, 0.6, 5], gap="small")

            with like_col:
                if st.button("👍", key=f"like_{i}", help="I like this", use_container_width=True):
                    if book_title in st.session_state.rejected_votes:
                        st.session_state.rejected_votes.remove(book_title)
                    st.session_state.liked_votes.add(book_title)
                    st.rerun()

            with reject_col:
                if st.button("👎", key=f"reject_{i}", help="Not for me", use_container_width=True):
                    if book_title in st.session_state.liked_votes:
                        st.session_state.liked_votes.remove(book_title)
                    st.session_state.rejected_votes.add(book_title)
                    st.rerun()

            with book_col:
                # Show book with visual feedback (2 lines: title+authors, description)
                line1 = f"**{i}. {book_title}**"
                if book_authors:
                    line1 += f" by {book_authors}"

                if book_title in st.session_state.liked_votes:
                    st.markdown(f"{line1} 💚")
                elif book_title in st.session_state.rejected_votes:
                    st.markdown(f"{line1} 💔")
                else:
                    st.markdown(line1)

                # Show description on second line
                if book_description:
                    st.caption(book_description)

        st.markdown("---")

        # Summary on the left with smaller font
        total_liked_col, total_rejected_col, total_selected_col, spacer_col = st.columns([0.5, 0.5, 0.5, 2.5], gap="small")

        with total_liked_col:
            st.metric("Liked", len(st.session_state.liked_votes))
        with total_rejected_col:
            st.metric("Rejected", len(st.session_state.rejected_votes))
        with total_selected_col:
            st.metric("Total", len(st.session_state.current_books))

        st.markdown("---")

        # Small submit button on the left
        submit_col, feedback_col = st.columns([0.05, 0.15])

        with submit_col:
            if st.button("✅ Submit", use_container_width=True):
                if st.session_state.liked_votes or st.session_state.rejected_votes:
                    with st.spinner("📤 Submitting feedback..."):
                        try:
                            response = submit_feedback(
                                user_email=st.session_state.user_email,
                                liked_titles=list(st.session_state.liked_votes),
                                rejected_titles=list(st.session_state.rejected_votes),
                                feedback_text=""
                            )

                            if response.get("success"):
                                st.session_state.feedback_submitted = True
                            else:
                                st.error(f"Error: {response.get('message')}")

                        except BackendError as e:
                            st.error(f"Error: {str(e)}")
                else:
                    st.warning("Select at least one book (👍 or 👎) before submitting")

        # Show feedback received message (smaller)
        if st.session_state.feedback_submitted:
            with feedback_col:
                st.markdown('<p style="font-size: 0.85rem; color: #31a049; margin: 0;">✅ Feedback received</p>', unsafe_allow_html=True)


# Main app logic
def main():
    if st.session_state.user_email is None:
        login_page()
    else:
        recommendations_page()


if __name__ == "__main__":
    main()
