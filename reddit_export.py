import csv
import re
import time
from urllib.parse import urljoin
from difflib import SequenceMatcher
import requests
import os
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================
SUBREDDIT = "smallbusiness"
STUDENT_NAMES = "First_Last"
NUM_STUDENTS = 1
TARGET_COMMENTS = 50 * NUM_STUDENTS

# AUTO-DISCOVERY SETTINGS
USE_AUTO_DISCOVERY = True  # Set to False to use manual THREAD_URLS only
PREVIEW_MODE = False  # Set to True to just preview discovered threads without scraping
DISCOVERY_LIMIT = 1000  # How many recent threads to check for discovery
DISCOVERY_SORT = "hot"  # Options: "hot" (best for finding active discussions), "new", "top"
MIN_COMMENTS_PER_THREAD = 10 # RELAXED: Skip threads with fewer comments than this (was 10)

# Manual thread URLs (used if USE_AUTO_DISCOVERY is False, or as a supplement)
MANUAL_THREAD_URLS = [
    "https://www.reddit.com/r/food/comments/3uwizf/how_do_i_eat_like_an_adult/",
    "https://www.reddit.com/r/food/comments/aqsdp/how_do_i_wean_myself_onto_spicy_food/",
    "https://www.reddit.com/r/food/comments/1fq6pop/help_im_craving_pizza_text/",
    "https://www.reddit.com/r/food/comments/1qd1anx/homemade_failed_cookies/",
    "https://www.reddit.com/r/food/comments/1ir9i7g/text_help_identifying_persian_cookiepastry/",
    "https://www.reddit.com/r/food/comments/1ekf79i/i_need_some_help_text/",
    "https://www.reddit.com/r/food/comments/2igs5w/as_a_child_i_hated_most_vegetables_as_an_adult_i/",
    "https://www.reddit.com/r/food/comments/1gol4mw/texthelp/",
    "https://www.reddit.com/r/food/comments/1pp0nnr/it_is_possible_to_like_every_single_food_and_if/",
    "https://www.reddit.com/r/food/comments/1oxa2pv/need_help_finding_a_food_i_ate_that_i_didnt_catch/",
    "https://www.reddit.com/r/food/comments/1jn157p/text_im_new_to_the_food_community_how_do_i_get/",
    "https://www.reddit.com/r/food/comments/444liv/i_cant_cook_rice_and_and_i_hate_its_stupid_face/",
    "https://www.reddit.com/r/food/comments/1oo2013/text_ideashelp/",
    "https://www.reddit.com/r/food/comments/1kjalgc/text_watermellon_is_disgusting_how_do_i_make_it/",
    "https://www.reddit.com/r/food/comments/9mtxz/i_am_a_beginning_cook_and_would_like_to_be_able/",
    "https://www.reddit.com/r/food/comments/1exwhnf/text_help_identifying_asian_noodle_dish/",
    "https://www.reddit.com/r/food/comments/1o35m6n/how_can_i_make_steak_enjoyable_to_eat_again_text/",
    "https://www.reddit.com/r/food/comments/1r368xd/is_there_a_website_i_can_put_ingredients_into_and/",
    "https://www.reddit.com/r/food/comments/1eiyxva/how_do_i_get_a_perfectly_crispy_thin_steak_text/",
]

OUTPUT_FOLDER = "RedditData_Output"
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)
    print(f"✓ Created folder: {OUTPUT_FOLDER}\n")
else:
    print(f"✓ Using existing folder: {OUTPUT_FOLDER}\n")

# FIXED FILENAMES (no timestamps - will be overwritten each run)
OUTFILE = os.path.join(OUTPUT_FOLDER, f"{STUDENT_NAMES}_RedditData_r_{SUBREDDIT}.csv")
ANALYSIS_FILE = os.path.join(OUTPUT_FOLDER, f"{STUDENT_NAMES}_pain_analysis.csv")
FAILURE_LOG = os.path.join(OUTPUT_FOLDER, f"{STUDENT_NAMES}_validation_failures.csv")
REJECTED_LOG = os.path.join(OUTPUT_FOLDER, f"{STUDENT_NAMES}_rejected_comments.csv")
REJECTED_THREADS_FILE = os.path.join(OUTPUT_FOLDER, "rejected_threads.txt")  # NEW: Persistent rejected threads
OPTIMIZED_URLS_FILE = os.path.join(OUTPUT_FOLDER, "optimized_thread_urls.txt")
DISCOVERED_URLS_FILE = os.path.join(OUTPUT_FOLDER, "discovered_thread_urls.txt")
SUMMARY_FILE = os.path.join(OUTPUT_FOLDER, "run_summary.txt")

MIN_SENTENCES = 2  # RELAXED from 3
MIN_CHARS = 150     # RELAXED from 180
MAX_CHARS = 2000
SIMILARITY_THRESHOLD = 0.75
PRE_RANK_MIN_SCORE = 6  # Raise floor to improve precision of accepted comments
RANKED_COMMENT_SCAN_LIMIT = 220  # Max ranked comments to evaluate per thread
STRICT_CLASSIFIER_MIN_SCORE = 6.0
ADAPTIVE_PRE_RANK_MIN_SCORE = 5.0
ADAPTIVE_CLASSIFIER_MIN_SCORE = 5.2
ADAPTIVE_RELAX_TRIGGER_PROGRESS = 0.55
ADAPTIVE_RELAX_MIN_COLLECTED_RATIO = 0.35
MIN_DISCOVERED_THREADS_AFTER_FILTER = 60  # Recover some rejected threads if filtering is too aggressive

UA = {"User-Agent": "SEVI39303-RedditData/1.0 (student project)"}

HARD_SKIP_THREAD_KEYWORDS = [
    "promote your business",
    "weekly thread",
    "daily thread",
    "megathread",
    "open thread",
    "showcase",
    "introduce yourself",
    "ama",
    "ask me anything",
]

# =============================================================================
# IMPROVED THREAD DISCOVERY SYSTEM
# =============================================================================

def discover_threads(subreddit, limit=1000, sort="new", min_comments=5):
    """
    Automatically discover threads from subreddit with IMPROVED keyword matching.
    Now uses a scoring system to find the BEST threads for pain/frustration content.
    SUPPORTS PAGINATION to fetch 1000+ threads (Reddit limit is 100 per request).
    
    Args:
        subreddit: Name of subreddit (without r/)
        limit: Number of threads to check (will make multiple requests if > 100)
        sort: "new", "hot", or "top"
        min_comments: Minimum comment count to consider
    
    Returns:
        List of thread dicts sorted by relevance score
    """
    print(f"\n🔍 Discovering threads from r/{subreddit} (sort={sort}, limit={limit})...")
    print(f"   Filtering for threads with {min_comments}+ comments...")
    
    # Reddit API limit is 100 per request, so we need pagination for > 100
    all_posts = []
    after = None
    requests_needed = (limit + 99) // 100  # Round up to nearest 100
    
    print(f"   📡 Making {requests_needed} request(s) to Reddit API (max 100 per request)...")
    
    for request_num in range(requests_needed):
        try:
            # Build URL with pagination
            url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit=100"
            if after:
                url += f"&after={after}"
            
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            data = r.json()
            
            # Extract posts
            children = data.get("data", {}).get("children", [])
            if not children:
                print(f"      ⚠ No more posts available after {len(all_posts)} posts")
                break
            
            all_posts.extend(children)
            
            # Get pagination token for next request
            after = data.get("data", {}).get("after")
            
            print(f"      Request {request_num + 1}/{requests_needed}: Got {len(children)} posts (total: {len(all_posts)})")
            
            # Stop if we've reached our limit or there's no more data
            if len(all_posts) >= limit or not after:
                break
            
            # Be polite - wait between requests
            if request_num < requests_needed - 1:
                time.sleep(1)  # Reduced from 2s
                
        except Exception as e:
            print(f"      ✗ Request {request_num + 1} failed: {e}")
            break
    
    print(f"\n   ✓ Retrieved {len(all_posts)} total posts from Reddit\n")
    
    # IMPROVED: Multi-tier keyword system with scoring
    
    # HIGH VALUE keywords (worth 10 points) - Strong pain/problem indicators
    HIGH_VALUE_KEYWORDS = [
        "can't", "cannot", "unable", "fail", "failed", "failing",
        "help me", "please help", "need help", "struggling",
        "frustrated", "frustrating", "annoying", "hate",
        "ruined", "disaster", "messed up", "went wrong",
        "what am i doing wrong", "why won't", "why can't",
        "losing money", "losing customers", "going bankrupt",
        "can't afford", "running out", "desperate",
    ]
    
    # MEDIUM VALUE keywords (worth 5 points) - Question/seeking help
    MEDIUM_VALUE_KEYWORDS = [
        "how do i", "how to", "how can i", "what do i",
        "why does", "why is", "any advice", "any tips",
        "need advice", "looking for help", "suggestions",
        "what should i", "does anyone know",
        "how should i", "where do i", "when should i",
    ]
    
    # LOW VALUE keywords (worth 3 points) - General problem indicators
    LOW_VALUE_KEYWORDS = [
        "help", "problem", "issue", "trouble", "difficulty",
        "question", "advice", "tips", "wrong", "bad",
        "don't know", "no idea", "confused", "understand",
        "concern", "worried", "stress", "challenge",
    ]
    
    # BUSINESS SPECIFIC keywords (worth 7 points) - Business-related problems
    BUSINESS_PROBLEM_KEYWORDS = [
        "cash flow", "not selling", "no sales", "no customers",
        "employees quit", "can't hire", "bad reviews", "competitor",
        "lawsuit", "legal issue", "tax problem", "irs",
        "slow season", "lost client", "customer complaint",
        "pricing problem", "too expensive", "undercutting",
        "marketing not working", "no leads", "overhead costs",
    ]
    
    # NEGATIVE keywords - Skip these threads (success stories, promos, spam)
    SKIP_KEYWORDS = [
        "revenue milestone", "just hit", "celebrating",
        "success story", "finally made it", "proud to announce",
        "check out my business", "shameless plug",
    ]

    # Soft penalty only; hard-skip list is global (HARD_SKIP_THREAD_KEYWORDS)
    SOFT_META_THREAD_KEYWORDS = [
        "share your",
        "promotion thread",
        "community thread",
        "networking thread",
    ]
    
    discovered = []
    discovery_stats = {
        "total_checked": 0,
        "matched": 0,
        "skipped_low_comments": 0,
        "skipped_keywords": 0,
        "skipped_meta_threads": 0,
        "skipped_no_match": 0
    }
    
    # Process all collected posts
    for post in all_posts:
        post_data = post["data"]
        title = post_data["title"]
        selftext = (post_data.get("selftext") or "").strip()
        searchable_text = f"{title} {selftext}".lower()
        num_comments = post_data.get("num_comments", 0)
        
        discovery_stats["total_checked"] += 1
        
        # Skip if too few comments
        if num_comments < min_comments:
            discovery_stats["skipped_low_comments"] += 1
            continue
        
        # Skip if contains negative keywords (these are usually show-off posts)
        if any(skip_word in searchable_text for skip_word in SKIP_KEYWORDS):
            discovery_stats["skipped_keywords"] += 1
            continue

        # Hard skip meta/promotional thread formats that rarely contain real pain narratives
        if any(meta_word in searchable_text for meta_word in HARD_SKIP_THREAD_KEYWORDS):
            discovery_stats["skipped_meta_threads"] += 1
            continue
        
        # Calculate relevance score
        score = 0
        matched_keywords = []
        
        # Check high value keywords
        for keyword in HIGH_VALUE_KEYWORDS:
            if keyword in searchable_text:
                score += 10
                matched_keywords.append(f"HIGH:{keyword}")
        
        # Check medium value keywords
        for keyword in MEDIUM_VALUE_KEYWORDS:
            if keyword in searchable_text:
                score += 5
                matched_keywords.append(f"MED:{keyword}")
        
        # Check low value keywords
        for keyword in LOW_VALUE_KEYWORDS:
            if keyword in searchable_text:
                score += 3
                matched_keywords.append(f"LOW:{keyword}")
        
        # Check business-specific keywords
        for keyword in BUSINESS_PROBLEM_KEYWORDS:
            if keyword in searchable_text:
                score += 7
                matched_keywords.append(f"BIZ:{keyword}")

        if "?" in title:
            score += 2
            matched_keywords.append("SIG:question_title")

        if re.search(r"\b(i|my|we|our)\b", searchable_text):
            score += 2
            matched_keywords.append("SIG:first_person_context")

        if len(selftext) >= 200:
            score += 1
            matched_keywords.append("SIG:detailed_context")

        if any(meta_word in searchable_text for meta_word in SOFT_META_THREAD_KEYWORDS):
            score -= 8
            matched_keywords.append("PENALTY:meta_thread")

        if score <= 0 and num_comments < (min_comments * 2):
            discovery_stats["skipped_no_match"] += 1
            continue
        
        # RELAXED: Include ALL threads that passed filters, even with score 0
        # (The pain detection will filter comments later)
        thread_url = f"https://www.reddit.com{post_data['permalink']}"
        discovered.append({
            "url": thread_url,
            "title": title,
            "score": post_data.get("score", 0),
            "num_comments": num_comments,
            "relevance_score": score,
            "matched_keywords": matched_keywords if matched_keywords else ["NONE:general"]
        })
        discovery_stats["matched"] += 1
    
    print(f"\n  📊 Discovery Statistics:")
    print(f"     Total checked: {discovery_stats['total_checked']}")
    print(f"     ✓ Matched: {discovery_stats['matched']}")
    print(f"     ✗ Skipped (< {min_comments} comments): {discovery_stats['skipped_low_comments']}")
    print(f"     ✗ Skipped (show-off posts): {discovery_stats['skipped_keywords']}")
    print(f"     ✗ Skipped (meta/promo threads): {discovery_stats['skipped_meta_threads']}")
    print(f"     ✗ Skipped (no keywords): {discovery_stats['skipped_no_match']}")
    
    # Prioritize pain relevance first, then engagement as a tie-breaker.
    print(f"\n  🎯 Sorting by pain relevance first, then engagement...")

    for thread in discovered:
        upvote_component = min(max(thread["score"], 0), 3000) / 250
        comment_component = min(thread["num_comments"], 400) / 20
        thread["combined_score"] = (
            (thread["relevance_score"] * 2.5) +   # Pain relevance dominates
            upvote_component +                    # Upvotes as weak signal
            comment_component                     # Comment volume as weak signal
        )
    
    # Sort by combined score (highest first)
    discovered.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return discovered

# =============================================================================
# PAIN/FRUSTRATION DETECTION SYSTEM
# =============================================================================

def sentence_count(text):
    """Count sentences in text."""
    return len(re.findall(r"[.!?]+", text))

def get_sentences(text):
    """Split text into sentences."""
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if s.strip()]

def low_quality_text_reason(text):
    """
    Detect low-coherence comments that often look like spam or word salad.
    Returns empty string when quality looks acceptable.
    """
    sentences = get_sentences(text)
    words = re.findall(r"[A-Za-z']+", text)
    if not sentences or not words:
        return "No meaningful content"

    sentence_word_counts = [len(re.findall(r"[A-Za-z']+", s)) for s in sentences]
    short_sentence_ratio = sum(1 for c in sentence_word_counts if c <= 4) / max(len(sentence_word_counts), 1)
    if len(sentences) >= 10 and short_sentence_ratio >= 0.5:
        return "Low coherence (too many short fragments)"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 8:
        short_line_ratio = sum(1 for line in lines if len(re.findall(r"[A-Za-z']+", line)) <= 4) / len(lines)
        if short_line_ratio >= 0.5:
            return "Low coherence (fragmented lines)"

    word_list = [w.lower() for w in words]
    unique_ratio = len(set(word_list)) / max(len(word_list), 1)
    if len(word_list) >= 140 and unique_ratio <= 0.28:
        return "Low lexical diversity"

    nonsense_markers = [
        "throttle throttle",
        "that'll do pig",
        "pork chops and applesauce",
    ]
    text_lower = text.lower()
    if any(marker in text_lower for marker in nonsense_markers):
        return "Low coherence (nonsense markers)"

    return ""

def is_hard_negative_comment(comment, body, thread_title):
    """Reject comments that are almost never useful customer-pain narratives."""
    text_lower = (body or "").lower()
    title_lower = (thread_title or "").lower()

    if any(keyword in title_lower for keyword in HARD_SKIP_THREAD_KEYWORDS):
        return True, "Meta/promo thread"

    distinguished = str((comment or {}).get("distinguished") or "").lower()
    if distinguished in {"moderator", "admin"}:
        return True, "Moderator/admin comment"
    if str((comment or {}).get("author") or "").lower() == "automoderator":
        return True, "AutoModerator comment"
    if (comment or {}).get("stickied"):
        return True, "Stickied moderator comment"

    moderator_notice_patterns = [
        r"\bplease report\b",
        r"\bthis post will be removed\b",
        r"\bif it looks like\b.{0,40}\bremoved\b",
        r"\bmod(erator)? team\b",
        r"\bthis thread\b.{0,30}\bspammers?\b",
    ]
    if any(re.search(pattern, text_lower) for pattern in moderator_notice_patterns):
        return True, "Moderator notice"

    service_pitch_patterns = [
        r"\bopen to a conversation\b",
        r"\b(i|we)\s+(help|support|coach|consult)\b",
        r"\bif you decide\b.{0,50}\b(i|we)\s+(step in|can help)\b",
        r"\bvisit\s+\S+\.\S+",
        r"\bdm me\b",
        r"\bcontact me\b",
    ]
    if any(re.search(pattern, text_lower) for pattern in service_pitch_patterns):
        return True, "Service pitch/self-promo"

    return False, ""

def rank_comment_pain_potential(text, thread_title="", comment=None):
    """
    Rank likely pain/frustration narratives before strict validation.
    Returns: (score, signals)
    """
    text_lower = text.lower()
    score = 0.0
    signals = []

    hard_negative, hard_negative_reason = is_hard_negative_comment(comment or {}, text, thread_title)
    if hard_negative:
        return -20.0, [f"hard_negative:{hard_negative_reason}"]

    quality_issue = low_quality_text_reason(text)
    if quality_issue:
        return -12.0, [f"low_quality:{quality_issue}"]

    first_person_hits = len(re.findall(r"\b(i|i'm|i’ve|ive|i've|me|my|mine|we|our|us)\b", text_lower))
    second_person_hits = len(re.findall(r"\b(you|your|you're|u)\b", text_lower))
    if first_person_hits >= 3:
        score += 4
        signals.append("first_person_strong")
    elif first_person_hits >= 1:
        score += 2
        signals.append("first_person")

    pain_terms = [
        "frustrated", "frustrating", "overwhelmed", "stressed", "stuck", "struggling",
        "can't", "cannot", "failed", "failing", "problem", "issue", "worried", "confused",
        "burned out", "burnout", "drowning", "killing us", "cash crunch",
    ]
    pain_term_hits = sum(1 for term in pain_terms if term in text_lower)
    if pain_term_hits > 0:
        score += min(pain_term_hits * 1.5, 12)
        signals.append("pain_language")

    impact_patterns = [
        r"(losing|lost|no|not enough)\s+(customers|clients|sales|revenue|money)",
        r"cash flow",
        r"can't (afford|hire|scale|pay|keep up)",
        r"(payroll|rent|overhead|expenses|costs)\s+(is|are)\s+(too high|killing|out of control|eating)",
        r"(employees|staff)\s+(quit|left|leaving|unreliable)",
        r"\bnet\s*(30|45|60|90)\b",
        r"\bout of pocket\b",
        r"\bfront(ing)?\s+(cash|costs|materials|labor)\b",
        r"\b(accounts?\s+receivable|ar)\b",
        r"\bline of credit\b",
    ]
    impact_hits = sum(1 for pattern in impact_patterns if re.search(pattern, text_lower))
    if impact_hits > 0:
        score += min(impact_hits * 3, 12)
        signals.append("business_impact")

    if re.search(r"\b(i|we)\s+(tried|attempted|have tried|did)\b.{0,90}\b(but|however|still)\b", text_lower):
        score += 3
        signals.append("attempt_failed")

    if re.search(r"\b(how do i|how can i|what should i do|need help|any advice)\b", text_lower):
        score += 2
        signals.append("help_request")

    sentences = get_sentences(text)
    first_sentence = sentences[0].lower() if sentences else ""
    advice_start_patterns = [
        r"^you (should|need to|have to|must|can|could)\s",
        r"^raise prices",
        r"^i recommend",
        r"^can you elaborate",
        r"^here('?s| is) what i do",
        r"^if i were you",
    ]
    if any(re.search(pattern, first_sentence) for pattern in advice_start_patterns):
        if first_person_hits <= 1:
            score -= 6
            signals.append("advice_penalty")

    if second_person_hits >= first_person_hits + 3 and second_person_hits >= 4:
        score -= 5
        signals.append("second_person_dominant")

    if any(token in text_lower for token in ["success story", "just hit", "milestone", "celebrating", "congrats"]):
        score -= 6
        signals.append("success_penalty")

    if re.search(r"https?://", text_lower):
        if re.search(r"\b(visit|buy|subscribe|checkout|check out|link in bio)\b", text_lower):
            score -= 4
            signals.append("promo_url_penalty")
        else:
            score -= 1

    title_tokens = set(re.findall(r"[a-z]{4,}", thread_title.lower()))
    if title_tokens:
        text_tokens = set(re.findall(r"[a-z]{4,}", text_lower))
        if len(title_tokens.intersection(text_tokens)) >= 2:
            score += 2
            signals.append("topic_overlap")

    return round(score, 1), signals

def is_substantive_pain_expression(text, thread_title="", min_score=STRICT_CLASSIFIER_MIN_SCORE):
    """
    Strict validation for customer pain/frustration comments.
    Returns: (is_pain, category, score, reason)
    """
    text_lower = text.lower()
    title_lower = (thread_title or "").lower()
    sentences = get_sentences(text)

    if len(sentences) < 2:
        return False, None, 0.0, "Less than 2 sentences"

    if any(keyword in title_lower for keyword in HARD_SKIP_THREAD_KEYWORDS):
        return False, None, 0.0, "Meta/promo thread"

    quality_issue = low_quality_text_reason(text)
    if quality_issue:
        return False, None, 0.0, quality_issue

    if "i am a bot" in text_lower or "this action was performed automatically" in text_lower:
        return False, None, 0.0, "Bot message"

    promo_patterns = [
        r"portfolio.*dribbble",
        r"packages? start at \$",
        r"feel free to contact me at",
        r"check out (my|our) (website|service|product)",
        r"\.myshopify\.com",
        r"\bbuy now\b",
        r"\bsubscribe\b",
        r"\bvisit\s+\S+\.\S+",
        r"\bdm me\b",
        r"\bcontact me\b",
    ]
    if any(re.search(pattern, text_lower) for pattern in promo_patterns):
        return False, None, 0.0, "Self-promotion"

    moderator_notice_patterns = [
        r"\bplease report\b",
        r"\bpost\b.{0,40}\bremoved\b",
        r"\bspammers?\b",
        r"\bthis thread\b.{0,40}\bpromotion\b",
    ]
    if any(re.search(pattern, text_lower) for pattern in moderator_notice_patterns):
        return False, None, 0.0, "Moderator notice"

    first_person_count = len(re.findall(r"\b(i|i'm|i’ve|ive|i've|me|my|mine|we|our|us)\b", text_lower))
    second_person_count = len(re.findall(r"\b(you|your|you're|u)\b", text_lower))
    first_sentence = sentences[0].lower()

    advice_start_patterns = [
        r"^you (should|need to|have to|must|can|could)\s",
        r"^raise prices",
        r"^i recommend",
        r"^can you elaborate",
        r"^here('?s| is) what i do",
        r"^if i were you",
    ]
    if any(re.search(pattern, first_sentence) for pattern in advice_start_patterns):
        if first_person_count <= 1:
            return False, None, 0.0, "Pure advice"

    if second_person_count >= first_person_count + 3 and second_person_count >= 4:
        return False, None, 0.0, "Advice-dominant (second-person)"

    # Third-person narratives are usually not direct customer pain from the speaker.
    if first_person_count == 0 and re.search(r"\b(he|she|they|my friend|my client|my cousin)\b", text_lower):
        return False, None, 0.0, "About someone else's experience"

    pain_score = 0.0
    matched_features = []

    own_context_patterns = [
        r"\bmy\s+(business|company|shop|practice|store|agency)\b",
        r"\b(i|we)\s+(run|own|manage|operate)\b",
    ]
    business_context_pattern = r"\b(business|company|shop|practice|store|agency|client|customer|revenue|sales|cash flow|payroll|invoice|supplier|vendor|employee|staff|profit|margin)\b"
    own_context = any(re.search(pattern, text_lower) for pattern in own_context_patterns) or (
        first_person_count >= 3 and re.search(business_context_pattern, text_lower)
    )
    if own_context:
        pain_score += 2.0
        matched_features.append("own_context")

    first_person_pain_patterns = [
        r"\bi\s+(can't|cannot|couldn't|am unable to|don't know how to)\b",
        r"\b(i'm|i am|we are)\s+(stuck|frustrated|overwhelmed|stressed|worried|exhausted|burned out)\b",
        r"\b(i|we)\s+(need|want|wish)\s+(help|advice|to fix|to solve|to figure out)\b",
        r"\b(i|we)\s+(regret|hate)\b",
        r"\b(i|we)\s+(have to|had to)\s+front\b",
        r"\b(i|we)\s+(keep|still)\s+(losing|fighting|dealing with)\b",
    ]
    fp_pain_hits = sum(1 for pattern in first_person_pain_patterns if re.search(pattern, text_lower))
    if fp_pain_hits:
        pain_score += fp_pain_hits * 2.2
        matched_features.append("first_person_pain")

    impact_patterns = [
        r"cash flow",
        r"(losing|lost|no|not enough)\s+(customers|clients|sales|revenue|money)",
        r"can't (afford|hire|scale|pay|keep up)",
        r"(payroll|rent|overhead|expenses|costs)\s+(is|are)\s+(killing|too high|eating|out of control)",
        r"(employees|staff)\s+(quit|left|leaving|unreliable)",
        r"bad reviews|chargebacks|refunds",
        r"\bnet\s*(30|45|60|90)\b",
        r"\bout of pocket\b",
        r"\bfront(ing)?\s+(cash|costs|materials|labor)\b",
        r"\b(accounts?\s+receivable|ar)\b",
        r"\bline of credit\b",
    ]
    impact_hits = sum(1 for pattern in impact_patterns if re.search(pattern, text_lower))
    if impact_hits:
        pain_score += impact_hits * 2.8
        matched_features.append("business_impact")

    unresolved_patterns = [
        r"\b(i|we)\b.{0,24}\b(still|yet|again|ongoing|keep)\b",
        r"\b(i|we)\b.{0,30}\b(didn't work|not working|can't|cannot|stuck|struggling|drowning)\b",
        r"\b(how do i|how can i|what should i do|any advice|does anyone know)\b",
    ]
    unresolved_hits = sum(1 for pattern in unresolved_patterns if re.search(pattern, text_lower))
    if unresolved_hits:
        pain_score += min(unresolved_hits * 1.2, 3.6)
        matched_features.append("unresolved")

    help_patterns = [
        r"\bhow do i\b|\bhow can i\b|\bwhat should i do\b",
        r"\bany advice\b|\bany tips\b|\bdoes anyone know\b",
    ]
    help_hits = sum(1 for pattern in help_patterns if re.search(pattern, text_lower))
    if help_hits:
        pain_score += min(help_hits * 1.3, 2.6)
        matched_features.append("help_request")

    if re.search(r"\b(i|we)\s+(tried|attempted|have tried|did)\b.{0,90}\b(but|however|still)\b", text_lower):
        pain_score += 1.8
        matched_features.append("attempt_failed")

    # Penalize advice-heavy language across the whole comment.
    advice_phrases = [
        r"\byou should\b",
        r"\byou could\b",
        r"\bi recommend\b",
        r"\byou need to\b",
        r"\bif i were you\b",
    ]
    advice_hits = sum(1 for pattern in advice_phrases if re.search(pattern, text_lower))
    if advice_hits:
        pain_score -= min(advice_hits * 1.5, 4.5)

    if any(token in text_lower for token in ["best decision i ever made", "worked great for me", "all good now"]):
        pain_score -= 2.5

    problem_signal = (fp_pain_hits + impact_hits + unresolved_hits) > 0
    needs_resolution = unresolved_hits > 0 or help_hits > 0 or re.search(r"\b(can't|cannot|stuck|struggling)\b", text_lower)

    if not own_context:
        return False, None, round(pain_score, 1), "No clear own-experience context"
    if not problem_signal:
        return False, None, round(pain_score, 1), "No concrete pain indicators"
    if not needs_resolution:
        return False, None, round(pain_score, 1), "Not clearly unresolved"
    if pain_score < min_score:
        return False, None, round(pain_score, 1), f"Pain score too low ({pain_score:.1f} < {min_score:.1f})"

    if re.search(r"\b(cash flow|payroll|overhead|expenses|margins?|revenue|profit|pricing|invoice|net\s*(30|45|60|90)|accounts?\s+receivable|line of credit)\b", text_lower):
        category = "cash_flow_finance"
    elif re.search(r"\b(hire|hiring|employee|staff|team|turnover|quit|recruit)\b", text_lower):
        category = "staffing"
    elif re.search(r"\b(systems?|process|workflow|manual|operations?|sop|accounting setup)\b", text_lower):
        category = "operations_systems"
    elif re.search(r"\b(marketing|ads?|leads?|seo|campaign|subscribers?|conversion)\b", text_lower):
        category = "marketing_growth"
    elif re.search(r"\b(tax|irs|legal|lawyer|lawsuit|compliance|contract)\b", text_lower):
        category = "legal_compliance"
    elif re.search(r"\b(exhausted|burned out|burnout|overwhelmed|stressed)\b", text_lower):
        category = "founder_burnout"
    elif re.search(r"\b(customer|client|refund|chargeback|review)\b", text_lower):
        category = "customer_management"
    else:
        category = "general_business_pain"

    return True, category, round(pain_score, 1), f"APPROVED ({', '.join(matched_features[:4])})"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_text(text):
    text = re.sub(r'http[s]?://\S+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower().strip()

def calculate_similarity(text1, text2):
    return SequenceMatcher(None, normalize_text(text1), normalize_text(text2)).ratio()

def is_too_similar(new_text, existing_texts):
    # OPTIMIZED: Only check last 50 texts (not all of them)
    # Most duplicates are close together anyway
    recent_texts = existing_texts[-50:] if len(existing_texts) > 50 else existing_texts
    
    for existing in recent_texts:
        if calculate_similarity(new_text, existing) >= SIMILARITY_THRESHOLD:
            return True
    return False

def flatten_comments(node, out):
    if isinstance(node, dict):
        kind = node.get("kind")
        data = node.get("data", {})
        if kind == "t1":
            body = (data.get("body") or "").strip()
            if body:
                out.append(data)
            replies = data.get("replies")
            if isinstance(replies, dict):
                flatten_comments(replies, out)
        elif kind == "Listing":
            for child in data.get("children", []):
                flatten_comments(child, out)


def fetch_thread(thread_url, max_retries=3):
    """Fetch thread with retry logic for rate limiting."""
    json_url = thread_url.rstrip("/") + "/.json?limit=500"
    
    for attempt in range(max_retries):
        try:
            r = requests.get(json_url, headers=UA, timeout=30)
            r.raise_for_status()
            payload = r.json()
            post = payload[0]["data"]["children"][0]["data"]
            title = post.get("title", "")
            comments = []
            flatten_comments(payload[1], comments)
            return title, comments
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limited
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3  # 3s, 6s, 9s
                    print(f"        ⏳ Rate limited, waiting {wait_time}s before retry {attempt + 2}/{max_retries}...")
                    time.sleep(wait_time)
                else:
                    raise  # Give up after max retries
            else:
                raise  # Other HTTP errors
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise

# =============================================================================
# MAIN LOGIC
# =============================================================================

print(f"Target: {TARGET_COMMENTS} SUBSTANTIVE pain/frustration comments")
print(f"Output folder: {OUTPUT_FOLDER}")
if not PREVIEW_MODE:
    print(f"NOTE: Files will be OVERWRITTEN with new data each run\n")

# =============================================================================
# LOAD PREVIOUSLY REJECTED THREADS
# =============================================================================

rejected_threads = set()
if os.path.exists(REJECTED_THREADS_FILE):
    try:
        with open(REJECTED_THREADS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    rejected_threads.add(line)
        print(f"✓ Loaded {len(rejected_threads)} previously rejected threads (will skip these)\n")
    except Exception as e:
        print(f"⚠ Could not load rejected threads: {e}\n")
else:
    print("✓ No rejected threads file found - first run\n")

# =============================================================================
# THREAD DISCOVERY & ASSEMBLY
# =============================================================================

print("=" * 70)
print("ASSEMBLING THREAD URLS...")
print("=" * 70)

THREAD_URLS = []

if USE_AUTO_DISCOVERY:
    discovered = discover_threads(
        SUBREDDIT, 
        limit=DISCOVERY_LIMIT, 
        sort=DISCOVERY_SORT,
        min_comments=MIN_COMMENTS_PER_THREAD
    )
    discovered_all = list(discovered)
    
    # FILTER OUT REJECTED THREADS
    discovered_before_filter = len(discovered)
    discovered = [item for item in discovered if item["url"] not in rejected_threads]
    filtered_count = discovered_before_filter - len(discovered)
    
    if filtered_count > 0:
        print(f"\n  🚫 Filtered out {filtered_count} previously rejected threads")
        print(f"  ✓ {len(discovered)} threads remaining after filter")

    # If too many URLs are filtered out, recover some high-scoring previously rejected threads.
    if len(discovered) < MIN_DISCOVERED_THREADS_AFTER_FILTER:
        needed = MIN_DISCOVERED_THREADS_AFTER_FILTER - len(discovered)
        recovered = [item for item in discovered_all if item["url"] in rejected_threads][:needed]
        if recovered:
            discovered.extend(recovered)
            print(f"  ♻ Re-added {len(recovered)} high-scoring previously rejected threads for re-check")
            print(f"  ✓ Total threads after recovery: {len(discovered)}")
    
    
    # SAVE discovered URLs with detailed info
    with open(DISCOVERED_URLS_FILE, "w", encoding="utf-8") as f:
        f.write(f"# Auto-discovered threads from r/{SUBREDDIT}\n")
        f.write(f"# Discovery date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Sort method: {DISCOVERY_SORT}\n")
        f.write(f"# Min comments filter: {MIN_COMMENTS_PER_THREAD}\n")
        f.write(f"# Total discovered: {len(discovered)}\n")
        f.write(f"# Sorted by: Pain relevance first, then engagement\n")
        f.write(f"# Formula: (relevance*2.5) + clipped_upvotes + clipped_comments\n\n")
        
        for i, item in enumerate(discovered, 1):
            f.write(f"#{i} (Combined Score: {item['combined_score']:.1f})\n")
            f.write(f"{item['url']}\n")
            f.write(f"  Title: {item['title']}\n")
            f.write(f"  Relevance: {item['relevance_score']} | Upvotes: {item['score']} | Comments: {item['num_comments']}\n")
            f.write(f"  Keywords: {', '.join(item['matched_keywords'][:5])}\n\n")
    
    print(f"\n✓ Saved discovered URLs to: {DISCOVERED_URLS_FILE}")
    print(f"\n📋 Top 10 Discovered Threads (by combined score):")
    print("=" * 70)
    for i, item in enumerate(discovered[:10], 1):
        print(f"\n{i}. [Score: {item['combined_score']:.1f}] {item['title'][:55]}...")
        print(f"   ↑{item['score']} upvotes | 💬{item['num_comments']} comments | 🎯{item['relevance_score']} relevance")
    
    THREAD_URLS = [item["url"] for item in discovered]
    print(f"\n✓ Using {len(THREAD_URLS)} auto-discovered threads (sorted by combined score)")
    
    # PREVIEW MODE - Just show discovered threads and exit
    if PREVIEW_MODE:
        print("\n" + "=" * 70)
        print("PREVIEW MODE - No scraping performed")
        print("=" * 70)
        print(f"\nFound {len(discovered)} threads. Check {DISCOVERED_URLS_FILE} for full list.")
        print("\nTo scrape these threads, set PREVIEW_MODE = False")
        print("\nDone!")
        exit(0)
else:
    THREAD_URLS = MANUAL_THREAD_URLS
    print(f"✓ Using {len(THREAD_URLS)} manual thread URLs")

# Rest of the script continues as before...
# (I'll include the complete scraping logic in the rest of the file)

rows = []
seen_ids = set()
seen_texts = []
validation_failures = []
rejected_comments = []
pain_category_counts = {}
thread_productivity = {}
ranking_stats = {
    "candidates_ranked": 0,
    "low_potential_filtered": 0,
    "hard_negative_filtered": 0,
    "adaptive_relaxed_threads": 0,
}

print("\n" + "=" * 70)
print("COLLECTING SUBSTANTIVE PAIN/FRUSTRATION COMMENTS...")
print("=" * 70)
print(f"Total threads to process: {len(THREAD_URLS)}")
print(f"Target: {TARGET_COMMENTS} comments")
print(f"💾 Auto-save enabled - CSV updates after each comment!\n")

relaxed_mode_announced = False

# =============================================================================
# INITIALIZE CSV FILES WITH HEADERS (AUTO-SAVE)
# =============================================================================

# Initialize main results file
with open(OUTFILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["ID", "Post Title", "Full Text", "URL", "Type"])
    writer.writeheader()
    writer.writerow({"ID": f"r/{SUBREDDIT}", "Post Title": "", "Full Text": "", "URL": "", "Type": ""})

# Initialize analysis file
analysis_fields = [
    "ID",
    "Post Title",
    "Full Text",
    "URL",
    "Type",
    "Pain_Category",
    "Pain_Score",
    "Classifier_Reason",
    "PreRank_Score",
    "PreRank_Signals",
]
with open(ANALYSIS_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=analysis_fields)
    writer.writeheader()

print(f"✓ Initialized output files with headers\n")

for thread_idx, url in enumerate(THREAD_URLS, 1):
    try:
        # Progress indicator
        progress = f"[{thread_idx}/{len(THREAD_URLS)}]"
        collected_so_far = len(rows)
        remaining = TARGET_COMMENTS - collected_so_far
        progress_ratio = thread_idx / max(len(THREAD_URLS), 1)
        collected_ratio = collected_so_far / max(TARGET_COMMENTS, 1)
        relaxed_threshold_mode = (
            progress_ratio >= ADAPTIVE_RELAX_TRIGGER_PROGRESS and
            collected_ratio < ADAPTIVE_RELAX_MIN_COLLECTED_RATIO
        )
        current_pre_rank_min = ADAPTIVE_PRE_RANK_MIN_SCORE if relaxed_threshold_mode else PRE_RANK_MIN_SCORE
        current_classifier_min = (
            ADAPTIVE_CLASSIFIER_MIN_SCORE if relaxed_threshold_mode else STRICT_CLASSIFIER_MIN_SCORE
        )
        if relaxed_threshold_mode:
            ranking_stats["adaptive_relaxed_threads"] += 1
            if not relaxed_mode_announced:
                print("\n⚙ Adaptive relaxed mode enabled to recover recall:")
                print(f"   pre-rank threshold: {PRE_RANK_MIN_SCORE} -> {current_pre_rank_min}")
                print(f"   classifier threshold: {STRICT_CLASSIFIER_MIN_SCORE} -> {current_classifier_min}")
                relaxed_mode_announced = True
        
        print(f"\n{progress} Processing thread (Collected: {collected_so_far}/{TARGET_COMMENTS}, Need: {remaining} more)...")
        
        # RATE LIMITING: Add delay before fetching to avoid 429 errors
        if thread_idx > 1:  # Skip delay for first thread
            time.sleep(2)  # Increased to 2 seconds between threads
        
        # Retry logic for 429 errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                title, comments = fetch_thread(url)
                break  # Success, exit retry loop
            except requests.exceptions.HTTPError as e:
                if '429' in str(e):
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                        print(f"  ⚠ Rate limited (429). Waiting {wait_time}s before retry {attempt + 2}/{max_retries}...")
                        time.sleep(wait_time)
                    else:
                        print(f"  ✗ Skipping thread after {max_retries} attempts (rate limited)")
                        raise
                else:
                    raise
        
        thread_count = 0
        thread_validation_failures = 0
        thread_rejected = 0
        
        MAX_PER_THREAD = 10  # OPTIMIZATION: Stop after 10 good comments per thread
        ranked_candidates = []
        low_potential_filtered = 0
        hard_negative_filtered = 0

        for c in comments:
            body = (c.get("body") or "").strip()
            cid = c.get("id", "")

            # Basic filters before ranking
            if not body or body in ["[deleted]", "[removed]"]:
                continue
            if cid in seen_ids:
                continue
            if len(body) < MIN_CHARS or len(body) > MAX_CHARS:
                continue
            if sentence_count(body) < MIN_SENTENCES:
                continue

            hard_negative, hard_negative_reason = is_hard_negative_comment(c, body, title)
            if hard_negative:
                hard_negative_filtered += 1
                continue

            pre_rank_score, pre_rank_signals = rank_comment_pain_potential(body, title, c)
            if pre_rank_score < current_pre_rank_min:
                low_potential_filtered += 1
                continue

            ranked_candidates.append({
                "comment": c,
                "body": body,
                "cid": cid,
                "pre_rank_score": pre_rank_score,
                "pre_rank_signals": pre_rank_signals,
                "reddit_score": c.get("score", 0),
            })

        ranking_stats["candidates_ranked"] += len(ranked_candidates)
        ranking_stats["low_potential_filtered"] += low_potential_filtered
        ranking_stats["hard_negative_filtered"] += hard_negative_filtered

        ranked_candidates.sort(
            key=lambda item: (item["pre_rank_score"], item["reddit_score"], len(item["body"])),
            reverse=True,
        )

        for candidate in ranked_candidates[:RANKED_COMMENT_SCAN_LIMIT]:
            c = candidate["comment"]
            body = candidate["body"]
            cid = candidate["cid"]
            pre_rank_score = candidate["pre_rank_score"]
            pre_rank_signals = candidate["pre_rank_signals"]

            if is_too_similar(body, seen_texts):
                continue

            # STRICT PAIN/FRUSTRATION DETECTION
            is_pain, category, score, reason = is_substantive_pain_expression(
                body, title, min_score=current_classifier_min
            )

            if not is_pain:
                thread_rejected += 1
                rejected_comments.append({
                    "comment_id": cid,
                    "thread": title[:50],
                    "reason": f"{reason} | pre_rank={pre_rank_score}",
                    "score": score,
                    "preview": body[:100] + "..."
                })
                continue

            permalink = c.get("permalink", "")
            full_url = urljoin("https://www.reddit.com", permalink)

            # Add to results
            comment_data = {
                "ID": cid,
                "Post Title": title,
                "Full Text": body,
                "URL": full_url,
                "Type": "Comment",
                "Pain_Category": category,
                "Pain_Score": score,
                "Classifier_Reason": reason,
                "PreRank_Score": pre_rank_score,
                "PreRank_Signals": ",".join(pre_rank_signals[:4]),
            }
            rows.append(comment_data)

            # AUTO-SAVE: Immediately append to CSV files
            with open(OUTFILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ID", "Post Title", "Full Text", "URL", "Type"])
                writer.writerow({
                    "ID": comment_data["ID"],
                    "Post Title": comment_data["Post Title"],
                    "Full Text": comment_data["Full Text"],
                    "URL": comment_data["URL"],
                    "Type": comment_data["Type"]
                })

            with open(ANALYSIS_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=analysis_fields)
                writer.writerow(comment_data)

            seen_ids.add(cid)
            seen_texts.append(body)
            thread_count += 1

            pain_category_counts[category] = pain_category_counts.get(category, 0) + 1

            # OPTIMIZATION: Exit early if we have enough from this thread
            if thread_count >= MAX_PER_THREAD:
                break

            if len(rows) >= TARGET_COMMENTS:
                break

        # TRACK THREAD PRODUCTIVITY
        thread_productivity[url] = {
            "title": title,
            "pain_comments": thread_count,
            "rejected": thread_rejected,
            "url_failures": thread_validation_failures,
            "ranked_candidates": len(ranked_candidates),
            "low_potential_filtered": low_potential_filtered,
            "hard_negative_filtered": hard_negative_filtered,
        }

        print(f"{progress} ✓ {title[:45]}...")
        print(
            f"        → Ranked {len(ranked_candidates)} candidates "
            f"(hard-negative: {hard_negative_filtered}, low-potential: {low_potential_filtered}, "
            f"pre-rank>= {current_pre_rank_min}, class>= {current_classifier_min})"
        )
        print(f"        → Collected {thread_count} pain comments from this thread")
        print(f"        → Total progress: {len(rows)}/{TARGET_COMMENTS} ({len(rows)/TARGET_COMMENTS*100:.1f}%)")

        if len(rows) >= TARGET_COMMENTS:
            print(f"\n🎉 TARGET REACHED! Collected {len(rows)} comments.")
            break

    except Exception as e:
        # Better error message
        error_msg = str(e)
        if "429" in error_msg:
            print(f"{progress} ⚠ Rate limited! Thread skipped (already retried 3 times)")
        else:
            print(f"{progress} ✗ Failed: {e}")
        
        thread_productivity[url] = {
            "title": "ERROR",
            "pain_comments": 0,
            "rejected": 0,
            "url_failures": 0
        }

print("\n" + "=" * 70)
print("COLLECTION COMPLETE")
print("=" * 70)
print(f"Total SUBSTANTIVE pain comments collected: {len(rows)}")
print(f"Total rejected (non-pain/advice): {len(rejected_comments)}")
print(f"Total URL validation failures: {len(validation_failures)}")
print(f"Ranked candidates evaluated: {ranking_stats['candidates_ranked']}")
print(f"Filtered hard-negatives: {ranking_stats['hard_negative_filtered']}")
print(f"Filtered early as low-potential: {ranking_stats['low_potential_filtered']}")
print(f"Threads using adaptive relaxed thresholds: {ranking_stats['adaptive_relaxed_threads']}")
if len(rows) > 0:
    print(f"\nPain/Frustration Category Breakdown:")
    for category, count in sorted(pain_category_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {category}: {count}")

# =============================================================================
# AUTOMATIC URL OPTIMIZATION
# =============================================================================

print("\n" + "=" * 70)
print("ANALYZING THREAD PRODUCTIVITY...")
print("=" * 70)

productive_urls = []
unproductive_urls = []

for url, stats in thread_productivity.items():
    if stats["pain_comments"] > 0:
        productive_urls.append(url)
        print(f"✓ KEEP: {stats['title'][:40]}... → {stats['pain_comments']} pain comments")
    else:
        unproductive_urls.append(url)
        print(f"✗ REMOVE: {stats['title'][:40]}... → 0 pain comments")

print(f"\n📊 Thread Analysis:")
print(f"  Productive threads: {len(productive_urls)}/{len(thread_productivity)}")
print(f"  Unproductive threads to remove: {len(unproductive_urls)}")

# =============================================================================
# UPDATE REJECTED THREADS FILE (PERSISTENT ACCUMULATION)
# =============================================================================

# Add new rejected threads to the existing set
for url in unproductive_urls:
    rejected_threads.add(url)

# Save complete rejected threads list
with open(REJECTED_THREADS_FILE, "w", encoding="utf-8") as f:
    f.write("# REJECTED THREADS - These threads yielded 0 pain comments\n")
    f.write("# This file is CUMULATIVE - threads accumulate across all runs\n")
    f.write(f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"# Total rejected threads: {len(rejected_threads)}\n")
    f.write(f"# New this run: {len(unproductive_urls)}\n\n")
    f.write("# These threads will be automatically skipped in future runs!\n\n")
    
    for url in sorted(rejected_threads):
        f.write(f"{url}\n")

if len(unproductive_urls) > 0:
    print(f"\n💾 Updated rejected threads file:")
    print(f"   Added {len(unproductive_urls)} new rejected threads")
    print(f"   Total rejected threads: {len(rejected_threads)}")
    print(f"   These will be skipped in future runs! ⚡")

# OVERWRITE optimized URL list
with open(OPTIMIZED_URLS_FILE, "w", encoding="utf-8") as f:
    f.write("# OPTIMIZED THREAD URLs - Only threads that yielded pain comments\n")
    f.write(f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"# Discovery method: {'Auto-discovery' if USE_AUTO_DISCOVERY else 'Manual'}\n")
    f.write(f"# Original threads: {len(thread_productivity)}\n")
    f.write(f"# Productive threads: {len(productive_urls)}\n")
    f.write(f"# Removed: {len(unproductive_urls)}\n\n")
    
    f.write("MANUAL_THREAD_URLS = [\n")
    for url in productive_urls:
        f.write(f'    "{url}",\n')
    f.write("]\n\n")
    
    if unproductive_urls:
        f.write("\n# REMOVED THREADS (yielded 0 pain comments):\n")
        for url in unproductive_urls:
            stats = thread_productivity[url]
            f.write(f'# "{url}"  # {stats["title"][:40]}...\n')

print(f"\n✓ Updated optimized URLs in: {OPTIMIZED_URLS_FILE}")

# =============================================================================
# SAVE SUPPLEMENTARY FILES (Main CSVs already auto-saved!)
# =============================================================================

print("\n" + "=" * 70)
print("SAVING SUPPLEMENTARY FILES...")
print("=" * 70)

# Main results and analysis already saved via auto-save!
print(f"✓ Main results already saved (auto-save): {OUTFILE}")
print(f"✓ Pain analysis already saved (auto-save): {ANALYSIS_FILE}")

# Save rejected comments log
with open(REJECTED_LOG, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["comment_id", "thread", "reason", "score", "preview"])
    writer.writeheader()
    for rejection in rejected_comments:
        writer.writerow(rejection)

print(f"✓ Saved rejected comments log to: {REJECTED_LOG}")

# OVERWRITE validation failures log
with open(FAILURE_LOG, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["comment_id", "url", "error", "thread"])
    writer.writeheader()
    for failure in validation_failures:
        writer.writerow(failure)

print(f"✓ Saved validation failures to: {FAILURE_LOG}")

# OVERWRITE summary file
with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
    f.write(f"Reddit Data Collection Summary - IMPROVED DISCOVERY\n")
    f.write(f"{'=' * 70}\n")
    f.write(f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"Subreddit: r/{SUBREDDIT}\n")
    f.write(f"Discovery mode: {'AUTO' if USE_AUTO_DISCOVERY else 'MANUAL'}\n")
    f.write(f"Target: {TARGET_COMMENTS} SUBSTANTIVE pain comments\n")
    f.write(f"Collected: {len(rows)} comments\n")
    f.write(f"Rejected: {len(rejected_comments)} (non-pain/advice)\n")
    f.write(f"URL Validation Failures: {len(validation_failures)}\n\n")
    f.write(f"Ranked candidates evaluated: {ranking_stats['candidates_ranked']}\n")
    f.write(f"Filtered hard-negatives: {ranking_stats['hard_negative_filtered']}\n")
    f.write(f"Filtered low-potential before strict check: {ranking_stats['low_potential_filtered']}\n")
    f.write(f"Threads using adaptive relaxed thresholds: {ranking_stats['adaptive_relaxed_threads']}\n\n")
    
    f.write(f"Thread Productivity Analysis:\n")
    f.write(f"  Productive threads: {len(productive_urls)}/{len(thread_productivity)}\n")
    f.write(f"  Unproductive threads: {len(unproductive_urls)}\n\n")
    
    if len(rows) > 0:
        f.write(f"Pain/Frustration Category Breakdown:\n")
        for category, count in sorted(pain_category_counts.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {category}: {count}\n")
    
    f.write(f"\nFiles (all updated each run):\n")
    f.write(f"  - {os.path.basename(OUTFILE)}\n")
    f.write(f"  - {os.path.basename(ANALYSIS_FILE)}\n")
    if USE_AUTO_DISCOVERY:
        f.write(f"  - {os.path.basename(DISCOVERED_URLS_FILE)}\n")
    f.write(f"  - {os.path.basename(OPTIMIZED_URLS_FILE)}\n")
    f.write(f"  - {os.path.basename(FAILURE_LOG)}\n")
    f.write(f"  - {os.path.basename(REJECTED_LOG)}\n")
    f.write(f"  - {os.path.basename(SUMMARY_FILE)}\n")

print(f"✓ Saved run summary to: {SUMMARY_FILE}")

print(f"\n{'=' * 70}")
print(f"All files updated in folder: {OUTPUT_FOLDER}")
print(f"{'=' * 70}")
if USE_AUTO_DISCOVERY:
    print("\n🎯 IMPROVED AUTO-DISCOVERY: Better keyword matching & scoring!")
    print(f"   Check {DISCOVERED_URLS_FILE} to see ranked threads.")
print(f"\n⭐ Optimized URLs available in: {OPTIMIZED_URLS_FILE}")
print("\n💡 TIP: Set PREVIEW_MODE = True to see discovered threads without scraping")
print("\n✅ All files overwritten with latest data!")
print("\nDone!")
