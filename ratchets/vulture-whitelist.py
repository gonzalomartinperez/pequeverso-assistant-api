"""Verified callback parameters required by standard-library interfaces (PVA-M2.2)."""

# HTMLParser.handle_starttag passes attributes even when only tag names are needed.
attrs  # noqa: B018, F821 -- Vulture whitelist references callback parameter names.
# HTTPRedirectHandler.redirect_request passes the response file object.
fp  # noqa: B018, F821 -- Vulture whitelist references callback parameter names.
# HTTPRedirectHandler.redirect_request supplies the response reason phrase.
msg  # noqa: B018, F821 -- Vulture whitelist references callback parameter names.
# HTTPRedirectHandler.redirect_request supplies the redirect target even when rejecting it.
newurl  # noqa: B018, F821 -- Vulture whitelist references callback parameter names.
