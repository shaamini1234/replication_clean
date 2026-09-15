# Companies House — API rate limit increase request

**Status:** draft, not sent.
**Send to:** xml@companieshouse.gov.uk
(General enquiries redirects rate-limit requests to this team — see
<https://forum.companieshouse.gov.uk/t/rate-limit-increase-request/12486>.)
**Suggested subject:** Rate limit increase request — academic research on UK business dynamism

---

Dear Companies House API team,

I am writing to request an increased rate limit on the Public Data API for a
non-commercial research project.

**Who we are**
British Progress is a research organisation studying UK economic performance.
I am the researcher responsible for this work and can be reached at
shaamini@britishprogress.org.

**What we are doing**
We are measuring UK business dynamism — firm entry and exit rates over time,
broken down by industry and geography. This requires, for each company that has
left the register, four fields: date of incorporation, date of cessation,
company status, and SIC code.

**Why we need the API**
Our working set is approximately 2.75 million dissolved and struck-off
companies. As far as we can establish, the Free Company Data Product covers
live companies only and there is no bulk product for dissolved companies, so
per-company API lookups are the only route to this data. We would much prefer a
bulk extract if one exists or could be made available — that would be lower
load for your infrastructure as well as faster for us.

**Our current position**
We hold several registered applications. We initially ran them in parallel and
found that all keys were rejected simultaneously with 401/403 responses roughly
four minutes into each run, while each individual key remained within its
600-requests-per-5-minutes allowance. We understood this as your systems
correctly objecting to the aggregate request rate from a single source, so we
stopped that approach immediately. We now run at approximately 4 requests per
second in total and have seen no further rejections.

At that rate the extraction takes about eight days of continuous running.

**What we are asking for**
Either of the following would help, and we are glad to take whichever suits you:

1. An increased rate limit on a single named application, so that we can
   consolidate onto one key rather than spreading load across several; or
2. Access to a bulk data extract covering dissolved companies, if such a
   product exists.

We are happy to provide the application name and key details, to sign any
appropriate data usage agreement, to state a specific ceiling we will not
exceed, and to schedule our requests for off-peak hours. We have no wish to
place undue load on your service and will continue to operate well within
whatever limit you set.

Thank you for your time, and for maintaining the register as open data.

Yours sincerely,

Shaamini Prinja
British Progress
shaamini@britishprogress.org

---

## Before sending — fill in

- [ ] Confirm the organisation description is how you want British Progress framed
- [ ] Add the registered application name(s) as they appear in your CH developer account
- [ ] Decide whether to name a specific target rate (e.g. 20 req/s) or let CH propose one
- [ ] Consider also posting to the developer forum — CH sometimes responds faster there

## Sources

- Rate limiting guide — <https://developer-specs.company-information.service.gov.uk/guides/rateLimiting>
  (read 2026-09-15): 600 requests / 5 minutes, applied per application; 429 on
  breach; *"We reserve the right to ban without notice applications that
  regularly exceed or attempt to bypass the rate limits."*
- Free Company Data Product — <https://download.companieshouse.gov.uk/en_output.html>
  (read 2026-09-15): monthly snapshot of live companies; does not include dissolved.
- Rate limit increase route — <https://forum.companieshouse.gov.uk/t/rate-limit-increase-request/12486>
  (read 2026-09-15): requests go to xml@companieshouse.gov.uk.
