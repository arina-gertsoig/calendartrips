def search_contacts(service, name: str) -> list[dict]:
    result = service.people().searchContacts(
        query=name,
        readMask="names,emailAddresses",
        pageSize=5,
    ).execute()

    contacts = []
    for item in result.get("results", []):
        person = item.get("person", {})
        names = [n.get("displayName", "") for n in person.get("names", [])]
        emails = [e.get("value", "") for e in person.get("emailAddresses", [])]
        if emails:
            contacts.append({
                "name": names[0] if names else "",
                "emails": emails,
            })

    return contacts
