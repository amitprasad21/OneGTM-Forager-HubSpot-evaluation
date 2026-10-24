"""In-memory stand-ins for HubSpotClient and ForagerClient used by service tests."""

import itertools

from app.credits import InMemoryCreditLedger


class FakeHubSpot:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.associations: dict[tuple[str, str, str], list[str]] = {}
        self.updates: list[tuple[str, str, dict]] = []
        self.created: list[tuple[str, dict, tuple | None]] = []
        self._ids = itertools.count(1000)

    def add(self, object_type: str, object_id: str, **properties) -> str:
        self.objects[(object_type, str(object_id))] = dict(properties)
        return str(object_id)

    def associate(self, company_id: str, contact_id: str) -> None:
        self.associations.setdefault(("companies", company_id, "contacts"), []).append(contact_id)
        self.associations.setdefault(("contacts", contact_id, "companies"), []).append(company_id)

    def props(self, object_type: str, object_id: str) -> dict:
        return self.objects[(object_type, str(object_id))]

    async def get_object(self, object_type, object_id, properties):
        stored = self.objects.get((object_type, str(object_id)))
        if stored is None:
            return None
        return {"id": str(object_id), "properties": {name: stored.get(name) for name in properties}}

    async def update_object(self, object_type, object_id, properties):
        self.updates.append((object_type, str(object_id), dict(properties)))
        self.objects[(object_type, str(object_id))].update(properties)
        return {"id": str(object_id), "properties": properties}

    async def create_object(self, object_type, properties, *, associate_with=None):
        object_id = str(next(self._ids))
        self.created.append((object_type, dict(properties), associate_with))
        self.objects[(object_type, object_id)] = dict(properties)
        if associate_with:
            self.associate(associate_with[1], object_id)
        return {"id": object_id, "properties": properties}

    async def find_by_property(self, object_type, property_name, value, properties):
        for (stored_type, object_id), stored in self.objects.items():
            if stored_type == object_type and value and stored.get(property_name) == value:
                return {"id": object_id, "properties": {name: stored.get(name) for name in properties}}
        return None

    async def list_associated_ids(self, from_type, from_id, to_type):
        return list(self.associations.get((from_type, str(from_id), to_type), []))

    async def associate_default(self, from_type, from_id, to_type, to_id):
        self.associate(to_id if from_type == "contacts" else from_id, from_id if from_type == "contacts" else to_id)


class FakeForager:
    def __init__(self, budget: int = 100):
        self.ledger = InMemoryCreditLedger(budget)
        self.organizations: list[dict] = []
        self.autocomplete: list[dict] = []
        self.role_results: list[dict] = []
        self.people: dict = {}  # keyed by person id and by linkedin slug
        self.people_by_email: dict[str, dict] = {}
        self.work_emails: dict = {}
        self.personal_emails: dict = {}
        self.phones: dict = {}
        self.calls: list[tuple[str, dict]] = []
        self.error: Exception | None = None

    def _call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error

    def called(self, name) -> list[dict]:
        return [kwargs for call, kwargs in self.calls if call == name]

    async def search_organizations(self, **kwargs):
        self._call("search_organizations", **kwargs)
        self.ledger.record(1, "organization_search")
        return {"search_results": self.organizations, "total_search_results": len(self.organizations)}

    async def autocomplete_organizations(self, query, page=1):
        self._call("autocomplete_organizations", query=query)
        return self.autocomplete

    async def search_person_roles(self, page=1, **filters):
        self._call("search_person_roles", page=page, **filters)
        self.ledger.record(1, "person_role_search")
        return {"search_results": self.role_results, "total_search_results": len(self.role_results)}

    async def get_person_detail(self, *, person_id=None, linkedin_slug=None):
        self._call("get_person_detail", person_id=person_id, linkedin_slug=linkedin_slug)
        person = self.people.get(person_id if person_id is not None else linkedin_slug)
        if person:
            self.ledger.record(1, "person_detail")
        return person

    async def reverse_lookup_email(self, email):
        self._call("reverse_lookup_email", email=email)
        person = self.people_by_email.get(email)
        if person:
            self.ledger.record(5, "reverse_email")
        return person

    async def find_work_email(self, **kwargs):
        self._call("find_work_email", **kwargs)
        email = self.work_emails.get(kwargs.get("linkedin_slug") or kwargs.get("last_name"))
        if email:
            self.ledger.record(5, "work_email")
        return email

    async def find_personal_email(self, *, person_id=None, linkedin_slug=None):
        self._call("find_personal_email", person_id=person_id, linkedin_slug=linkedin_slug)
        email = self.personal_emails.get(person_id)
        if email:
            self.ledger.record(5, "personal_email")
        return email

    async def find_phone(self, *, person_id=None, linkedin_slug=None):
        self._call("find_phone", person_id=person_id, linkedin_slug=linkedin_slug)
        self.ledger.ensure_available(15)
        phone = self.phones.get(person_id)
        if phone:
            self.ledger.record(15, "phone")
        return phone
