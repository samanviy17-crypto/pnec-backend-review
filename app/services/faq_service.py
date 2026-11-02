# app/services/faq_service.py
# Responsibility: FAQ business logic — fetch categories, items, search, submit questions.
# Routes call these workers; no Flask request/response objects here.

from datetime import datetime
from app import db
from app.models.faq import FaqCategory, FaqItem, UserQuestion


def get_all_categories():
    """
    Purpose: Retrieve all FAQ categories ordered for display.
    @returns {list} List of FaqCategory dicts sorted by display_order
    Algorithm:
    1. Query all categories
    2. Order by display_order ascending
    3. Return as list of dicts
    """
    categories = FaqCategory.query.order_by(FaqCategory.display_order).all()
    return [c.to_dict() for c in categories]


def get_items_for_category(category_id):
    """
    Purpose: Retrieve all FAQ items belonging to a category.
    @param {int} category_id - The category FK to filter by
    @returns {list} List of FaqItem dicts, empty list if category not found
    Algorithm:
    1. Verify category exists
    2. Query items by category_id
    3. Return list of dicts
    """
    category = FaqCategory.query.get(category_id)
    if not category:
        return []
    items = FaqItem.query.filter_by(category_id=category_id).all()
    return [i.to_dict() for i in items]


def search_faq(query_text):
    """
    Purpose: Full-text search across FAQ question and answer fields.
    @param {str} query_text - The search string from the user
    @returns {list} List of matching FaqItem dicts (up to 20 results)
    Algorithm:
    1. Sanitize and validate query
    2. Build LIKE filter on question and answer fields
    3. Limit to 20 results to keep response small
    4. Return list of dicts with category info
    """
    if not query_text or len(query_text.strip()) < 2:
        return []

    term = f'%{query_text.strip()}%'
    items = (FaqItem.query
             .filter(db.or_(FaqItem.question.ilike(term), FaqItem.answer.ilike(term)))
             .limit(20)
             .all())

    results = []
    for item in items:
        d = item.to_dict()
        d['category_name'] = item.category.name if item.category else ''
        d['category_icon'] = item.category.icon if item.category else ''
        results.append(d)
    return results


def increment_helpful(item_id):
    """
    Purpose: Increment the helpful_count for a FAQ item by 1.
    @param {int} item_id - The FAQ item to mark as helpful
    @returns {bool} True on success, False if item not found
    Algorithm:
    1. Fetch item by id
    2. Increment helpful_count
    3. Commit and return success flag
    """
    item = FaqItem.query.get(item_id)
    if not item:
        return False
    item.helpful_count += 1
    db.session.commit()
    return True


def submit_question(display_name, email, question_text, user_id=None):
    """
    Purpose: Save a user-submitted question for staff review.
    @param {str}      display_name  - Submitter's name (required)
    @param {str}      email         - Contact email for the response
    @param {str}      question_text - The question content
    @param {int|None} user_id       - FK to users table (if logged in)
    @returns {tuple} (UserQuestion dict, None) on success, (None, error_key) on failure
    Algorithm:
    1. Validate required fields
    2. Create UserQuestion with status='open'
    3. Persist and return dict
    """
    if not display_name or not email or not question_text:
        return None, 'VALIDATION_FAILED'

    q = UserQuestion(
        display_name=display_name.strip(),
        email=email.strip().lower(),
        question_text=question_text.strip(),
        status=UserQuestion.STATUS_OPEN,
        user_id=user_id,
    )
    db.session.add(q)
    db.session.commit()
    return q.to_dict(), None


def get_all_questions(status_filter=None):
    """
    Purpose: Retrieve all user-submitted questions (staff-only view).
    @param {str|None} status_filter - Optional status to filter by ('open', 'claimed', 'answered')
    @returns {list} List of UserQuestion dicts, newest first
    """
    query = UserQuestion.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    questions = query.order_by(UserQuestion.created_at.desc()).all()
    return [q.to_dict() for q in questions]


def claim_question(question_id, staff_user_id):
    """
    Purpose: Mark an open question as claimed by a staff member.
    @param {int} question_id   - The question to claim
    @param {int} staff_user_id - The staff member's user id
    @returns {tuple} (dict, None) on success, (None, error_key) on failure
    Algorithm:
    1. Fetch question
    2. Validate it is still 'open'
    3. Set status='claimed' and claimed_by_staff_id
    4. Commit and return
    """
    q = UserQuestion.query.get(question_id)
    if not q:
        return None, 'NOT_FOUND'
    if q.status != UserQuestion.STATUS_OPEN:
        return None, 'VALIDATION_FAILED'
    q.status = UserQuestion.STATUS_CLAIMED
    q.claimed_by_staff_id = staff_user_id
    db.session.commit()
    return q.to_dict(), None


def answer_question(question_id, answer_text, staff_user_id):
    """
    Purpose: Submit a staff answer to a claimed question.
    @param {int} question_id   - The question to answer
    @param {str} answer_text   - The staff's written answer
    @param {int} staff_user_id - Staff member's user id (must have claimed it)
    @returns {tuple} (dict, None) on success, (None, error_key) on failure
    Algorithm:
    1. Fetch question and validate state
    2. Ensure the answering staff is the one who claimed it (or admin)
    3. Set status='answered', answer_text, and answered_at
    4. Commit and return
    """
    q = UserQuestion.query.get(question_id)
    if not q:
        return None, 'NOT_FOUND'
    if not answer_text or not answer_text.strip():
        return None, 'VALIDATION_FAILED'
    q.status = UserQuestion.STATUS_ANSWERED
    q.answer_text = answer_text.strip()
    q.answered_at = datetime.utcnow()
    if not q.claimed_by_staff_id:
        q.claimed_by_staff_id = staff_user_id
    db.session.commit()
    return q.to_dict(), None


def seed_faq():
    """
    Purpose: Populate the FAQ categories and items with PNEC preparedness content.
    Only runs if no categories exist yet. Safe to call on every app startup.
    @returns {int} Number of categories inserted
    Algorithm:
    1. Check if categories already exist — skip if so
    2. Insert all categories with display_order
    3. Insert all FAQ items linked to their categories
    4. Commit and return count
    """
    if FaqCategory.query.first():
        return 0

    seed_data = [
        {
            'name': 'Wildfire', 'icon': '🔥', 'order': 1,
            'items': [
                ('What should I do if I receive an evacuation order?',
                 'Leave immediately — do not wait. Grab your pre-packed go-bag, load pets, and take your planned evacuation route. Do not stop to pack more belongings. Notify family of your destination. Time is the most critical factor in a wildfire evacuation.'),
                ('How do I find my evacuation zone?',
                 'Poway uses an A-D zone system tied to fire risk areas. Zone A is highest risk and evacuates first. Find your zone at the San Diego County Office of Emergency Services website or enter your address at readysandiego.org. Know your zone BEFORE a fire starts.'),
                ('What should be in my go-bag for wildfire evacuation?',
                 'A wildfire go-bag should include: water (at least 1 gallon per person), medications, important documents (ID, insurance, bank info), phone chargers, cash, change of clothes, N95 masks for smoke, pet food and carriers, and a battery-powered radio.'),
                ('How do I protect my home before leaving?',
                 'If time allows and it is safe: close all windows and doors, move combustible furniture to center of rooms, leave exterior lights on so your home is visible in smoke, shut off gas at the meter, connect garden hoses to outdoor faucets, and remove flammable items from decks.'),
                ('Where are Poway evacuation routes?',
                 'Primary routes: Poway Road westbound to I-15, Community Road to SR-56. Alternate: Scripps Poway Parkway west. Always follow directions from San Diego County Sheriff deputies and CalFire. Tune to KOGO 600 AM for road status.'),
            ],
        },
        {
            'name': 'Flood & Rain', 'icon': '🌊', 'order': 2,
            'items': [
                ('What should I do if my street is flooding?',
                 'Stay off flooded roads and turn around — never drive through standing or moving water. Move to higher ground if water is rising near your home. Call 911 only for life-threatening emergencies. Monitor San Diego County flood alerts at readysandiego.org.'),
                ('Is it safe to drive through flooded roads?',
                 'No. Just 6 inches of moving water can knock an adult off their feet. 12 inches can sweep away a small vehicle. 2 feet will carry away most cars. "Turn Around, Don\'t Drown" is the rule — no exception.'),
                ('How do I prepare for heavy rain season?',
                 'Before rain season (November-April): clean gutters and downspouts, check your roof for damage, know your flood zone, build a 72-hour kit, identify your nearest high ground, and sign up for AlertSanDiego emergency notifications at alertsandiego.org.'),
                ('What are the flood-prone areas in Poway?',
                 'Areas near Poway Creek, the Poway Road corridor near Community Road, and low-lying areas east of Poway Road are most prone to flooding. Drainage channels can overflow quickly during heavy rain. Know your flood risk zone.'),
            ],
        },
        {
            'name': 'Earthquake', 'icon': '🌍', 'order': 3,
            'items': [
                ('What should I do during an earthquake?',
                 'DROP to the ground, take COVER under a sturdy desk or table (or against an interior wall away from windows), and HOLD ON until shaking stops. Stay inside. Do not run outside — most injuries happen from falling debris near building exits.'),
                ('How do I prepare my home for earthquakes?',
                 'Secure heavy furniture to walls (bookcases, water heaters, refrigerators). Store heavy items on lower shelves. Know where your gas, water, and electricity shutoffs are. Keep a 72-hour kit. Practice your household plan.'),
                ('What is Drop, Cover, and Hold On?',
                 'Drop to your hands and knees to prevent being knocked down. Take Cover under a sturdy table or desk — this protects your head and neck. If no table is near, cover your head with your arms and crouch near an interior wall. Hold On to shelter until shaking stops.'),
                ('How do I shut off my gas after an earthquake?',
                 'Shut off gas ONLY if you smell gas, hear hissing, or see a damaged line. Use an adjustable wrench to turn the valve a quarter-turn so it is perpendicular to the pipe. Once off, only the utility company can turn it back on. Keep a wrench near your gas meter.'),
            ],
        },
        {
            'name': 'Extreme Heat', 'icon': '🌡️', 'order': 4,
            'items': [
                ('What temperature is considered dangerous?',
                 'Heat exhaustion risk begins above 90F, especially with high humidity. Heat stroke — a life-threatening emergency — can occur above 104F. The elderly, infants, outdoor workers, and those with chronic illness are most vulnerable.'),
                ('Where are cooling centers in Poway?',
                 'During excessive heat warnings, the City of Poway opens cooling centers at City Hall (13325 Civic Center Dr) and the Poway Community Park recreation center. Visit 211sandiego.org or call 2-1-1 for the current list.'),
                ('How do I check on vulnerable neighbors during a heat wave?',
                 'Know your elderly, chronically ill, and isolated neighbors. Visit or call them at least twice daily during heat emergencies. Watch for signs of heat stroke: hot and dry skin, confusion, slurred speech, loss of consciousness. Call 911 immediately.'),
            ],
        },
        {
            'name': '72-Hour Kit', 'icon': '📦', 'order': 5,
            'items': [
                ('What goes in a 72-hour emergency kit?',
                 'FEMA recommends: water (1 gallon/person/day x 3 days), 3-day food supply of non-perishable items, battery-powered or hand crank radio, flashlight, first aid kit, whistle, dust masks or N95s, plastic sheeting and duct tape, moist towelettes, garbage bags, wrench or pliers, manual can opener, local maps, and phone chargers.'),
                ('How much water do I need per person?',
                 'FEMA recommends 1 gallon per person per day for at least 3 days. A family of 4 needs 12 gallons minimum. Store more in hot weather or for medical needs. Use PETE plastic bottles or commercial water containers. Replace stored water every 6-12 months.'),
                ('What documents should I keep in my kit?',
                 'Store copies (in waterproof bags) of: government-issued ID, passport, Social Security cards, insurance policies, bank account numbers, deed or lease, medication list and prescriptions, contact numbers, and photos of household members.'),
                ('How often should I update my kit?',
                 'Review your kit twice a year — when you change smoke detector batteries is a good reminder. Check expiration dates on food and water. Replace medications. Update documents. Rotate clothing seasonally.'),
            ],
        },
        {
            'name': 'Neighborhood Coordinators', 'icon': '🏘️', 'order': 6,
            'items': [
                ('What is a Neighborhood Emergency Coordinator?',
                 'A Neighborhood Emergency Coordinator (NEC) is a trained PNEC volunteer who serves as the liaison between their neighborhood and PNEC during disasters. They conduct neighborhood surveys, connect residents with resources, and maintain contact lists.'),
                ('How do I find my coordinator?',
                 'Use the PNEC Neighborhood Map to find your neighborhood number and coordinator contact information. If no coordinator is listed for your area, that neighborhood has a vacancy. You can also contact PNEC directly at contact@example.test.'),
                ('How do I become a coordinator?',
                 'Contact PNEC at contact@example.test or attend a community preparedness meeting. Coordinators complete a short orientation, learn their neighborhood geography and vulnerable residents, and attend periodic PNEC trainings. No prior emergency experience required.'),
                ('What does PNEC do?',
                 'PNEC — Poway Neighborhood Emergency Corps — has been preparing Poway residents since 2011. We organize neighborhoods into emergency zones with trained coordinators, run CERT training, support the PACT ham radio program, host preparedness fairs, and coordinate with the City of Poway and San Diego County OES.'),
            ],
        },
        {
            'name': 'Ham Radio & PACT', 'icon': '📻', 'order': 7,
            'items': [
                ('What is PACT?',
                 'PACT — the Poway Amateur Communications Team — is PNEC\'s ham radio volunteer program. PACT operators provide emergency communications when cell towers and internet go down. They train regularly with city and county emergency management agencies.'),
                ('How do ham radio operators help during emergencies?',
                 'Ham radio works without cell towers or internet infrastructure. PACT operators can relay messages between neighborhoods and the Emergency Operations Center, check on isolated residents, support search and rescue teams, and bridge communication gaps when every other system has failed.'),
                ('How do I get a ham radio license?',
                 'The FCC Technician License exam is a 35-question test — no Morse code required. Study free at HamStudy.org or ARRL.org. Exams are regularly offered in the San Diego area. Once licensed, contact PACT at contact@example.test to get involved.'),
            ],
        },
        {
            'name': 'Volunteering', 'icon': '🙋', 'order': 8,
            'items': [
                ('How do I volunteer with PNEC?',
                 'PNEC always needs volunteers! Opportunities include Neighborhood Emergency Coordinator, CERT team member, PACT ham radio operator, event support, and administrative help. Visit our Volunteer page or email contact@example.test. No experience required.'),
                ('What is CERT training?',
                 'CERT — Community Emergency Response Team — is a FEMA program that trains community members in basic disaster response skills: fire safety, light search and rescue, triage, and first aid. The course is about 24 hours total, offered by the City of Poway and San Diego County.'),
                ('How do I donate to PNEC?',
                 'PNEC is a 501(c)(3) nonprofit organization. Donations fund training programs, community outreach, equipment, and coordinator support. Donate online at powaynec.com/donate or mail a check to PNEC, PO Box 1664, Poway, CA 92074. All donations are tax-deductible.'),
            ],
        },
    ]

    count = 0
    for cat_data in seed_data:
        category = FaqCategory(
            name=cat_data['name'],
            icon=cat_data['icon'],
            display_order=cat_data['order'],
        )
        db.session.add(category)
        db.session.flush()

        for question, answer in cat_data['items']:
            from flask import current_app
            contact=current_app.config.get('PUBLIC_CONTACT_EMAIL')
            if contact:answer=answer.replace('contact@example.test',contact)
            item = FaqItem(
                category_id=category.id,
                question=question,
                answer=answer,
                helpful_count=0,
            )
            db.session.add(item)

        count += 1

    db.session.commit()
    return count
