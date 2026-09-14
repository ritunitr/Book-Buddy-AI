"""
Book-Buddy-AI Streamlit App
Multi-page app with login and recommendations
"""

import streamlit as st
from api_client import get_recommendations, submit_feedback, BackendError, DEMO_MODE

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


def login_page():
    """Login/welcome page to collect user email."""
    st.markdown("# 📚 Book-Buddy-AI")
    st.markdown("## Get personalized book recommendations")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
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
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**User:** {st.session_state.user_email}")
    with col2:
        if st.button("Logout", key="logout"):
            st.session_state.user_email = None
            st.session_state.current_books = []
            st.session_state.liked_votes = set()
            st.session_state.rejected_votes = set()
            st.rerun()

    st.markdown("---")

    # Query input
    st.markdown("### What kind of books are you looking for?")
    query = st.text_input(
        "Book recommendation query",
        placeholder="e.g., Fantasy books with dragons, or sci-fi about AI...",
        key="query_input"
    )

    if st.button("Get Recommendations", use_container_width=True, type="primary"):
        if query:
            with st.spinner("🔍 Finding recommendations..."):
                try:
                    response = get_recommendations(query)
                    books = []

                    if response.get("request_type") == "progression":
                        for level in response.get("levels", []):
                            for rec in level.get("recommendations", []):
                                books.append(rec.get("title", "Unknown"))
                    else:
                        for rec in response.get("recommendations", []):
                            books.append(rec.get("title", "Unknown"))

                    st.session_state.current_books = books
                    st.session_state.liked_votes = set()
                    st.session_state.rejected_votes = set()
                    st.success(f"✨ Found {len(books)} recommendations!")

                except BackendError as e:
                    st.error(f"Error: {str(e)}")
        else:
            st.warning("Please enter a book recommendation query")

    st.markdown("---")

    # Display recommendations with vote buttons
    if st.session_state.current_books:
        st.markdown("### Rate these recommendations")
        st.markdown("Click 👍 to like or 👎 to reject")

        for i, book in enumerate(st.session_state.current_books, 1):
            col1, col2, col3 = st.columns([0.5, 0.5, 4])

            with col1:
                if st.button("👍", key=f"like_{i}", help="I like this"):
                    if book in st.session_state.rejected_votes:
                        st.session_state.rejected_votes.remove(book)
                    st.session_state.liked_votes.add(book)
                    st.rerun()

            with col2:
                if st.button("👎", key=f"reject_{i}", help="Not for me"):
                    if book in st.session_state.liked_votes:
                        st.session_state.liked_votes.remove(book)
                    st.session_state.rejected_votes.add(book)
                    st.rerun()

            with col3:
                # Show book with visual feedback
                if book in st.session_state.liked_votes:
                    st.markdown(f"**{i}. {book}** 💚")
                elif book in st.session_state.rejected_votes:
                    st.markdown(f"**{i}. {book}** 💔")
                else:
                    st.markdown(f"**{i}. {book}**")

        st.markdown("---")

        # Summary and submit button
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Liked", len(st.session_state.liked_votes))
        with col2:
            st.metric("Rejected", len(st.session_state.rejected_votes))
        with col3:
            st.metric("Total", len(st.session_state.current_books))

        st.markdown("---")

        if st.button("✅ Submit Feedback", use_container_width=True, type="primary"):
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
                            st.success(f"✅ Feedback recorded!")
                            if response.get("summarizer_triggered"):
                                st.info("🧠 Your profile is being updated with your preferences...")
                            st.session_state.current_books = []
                            st.session_state.liked_votes = set()
                            st.session_state.rejected_votes = set()
                            st.rerun()
                        else:
                            st.error(f"Error: {response.get('message')}")

                    except BackendError as e:
                        st.error(f"Error: {str(e)}")
            else:
                st.warning("Select at least one book (👍 or 👎) before submitting")


# Main app logic
def main():
    if st.session_state.user_email is None:
        login_page()
    else:
        recommendations_page()


if __name__ == "__main__":
    main()
