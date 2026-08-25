-- ============================================================================
-- 11_add_region.sql — add UK region to firm_master (and companies) from postcode
-- Run:  psql business_dynamism -f 11_add_region.sql
--
-- Region derived from postcode AREA (the leading letters). Approximate — precise
-- region/local-authority needs the ONS Postcode Directory (a separate download).
-- Covers live firms (postcode comes from the companies snapshot); dead firms that
-- have left the register have no postcode here (their region can be recovered
-- from Gazette notice text separately).
-- ============================================================================

DROP TABLE IF EXISTS postcode_region;
CREATE TABLE postcode_region(area text PRIMARY KEY, region text);
INSERT INTO postcode_region(area,region) VALUES
 ('E','London'),('EC','London'),('N','London'),('NW','London'),('SE','London'),('SW','London'),('W','London'),('WC','London'),
 ('BR','London'),('CR','London'),('DA','London'),('EN','London'),('HA','London'),('IG','London'),('KT','London'),('RM','London'),('SM','London'),('TW','London'),('UB','London'),('WD','London'),
 ('BN','South East'),('CT','South East'),('GU','South East'),('ME','South East'),('MK','South East'),('OX','South East'),('PO','South East'),('RG','South East'),('RH','South East'),('SL','South East'),('SO','South East'),('TN','South East'),
 ('BA','South West'),('BH','South West'),('BS','South West'),('DT','South West'),('EX','South West'),('GL','South West'),('PL','South West'),('TA','South West'),('TQ','South West'),('TR','South West'),('SN','South West'),('SP','South West'),
 ('AL','East of England'),('CB','East of England'),('CM','East of England'),('CO','East of England'),('IP','East of England'),('LU','East of England'),('NR','East of England'),('PE','East of England'),('SG','East of England'),('SS','East of England'),
 ('B','West Midlands'),('CV','West Midlands'),('DY','West Midlands'),('WS','West Midlands'),('WV','West Midlands'),('WR','West Midlands'),('TF','West Midlands'),('ST','West Midlands'),
 ('DE','East Midlands'),('LE','East Midlands'),('LN','East Midlands'),('NG','East Midlands'),('NN','East Midlands'),
 ('BD','Yorkshire & Humber'),('DN','Yorkshire & Humber'),('HD','Yorkshire & Humber'),('HG','Yorkshire & Humber'),('HU','Yorkshire & Humber'),('HX','Yorkshire & Humber'),('LS','Yorkshire & Humber'),('S','Yorkshire & Humber'),('WF','Yorkshire & Humber'),('YO','Yorkshire & Humber'),
 ('BB','North West'),('BL','North West'),('CA','North West'),('CH','North West'),('CW','North West'),('FY','North West'),('L','North West'),('LA','North West'),('M','North West'),('OL','North West'),('PR','North West'),('SK','North West'),('WA','North West'),('WN','North West'),
 ('DH','North East'),('DL','North East'),('NE','North East'),('SR','North East'),('TS','North East'),
 ('CF','Wales'),('LD','Wales'),('LL','Wales'),('NP','Wales'),('SA','Wales'),('SY','Wales'),
 ('AB','Scotland'),('DD','Scotland'),('DG','Scotland'),('EH','Scotland'),('FK','Scotland'),('G','Scotland'),('HS','Scotland'),('IV','Scotland'),('KA','Scotland'),('KW','Scotland'),('KY','Scotland'),('ML','Scotland'),('PA','Scotland'),('PH','Scotland'),('TD','Scotland'),('ZE','Scotland'),
 ('BT','Northern Ireland');

ALTER TABLE firm_master ADD COLUMN IF NOT EXISTS region text;
UPDATE firm_master f SET region = pr.region
FROM companies c
JOIN postcode_region pr ON pr.area = substring(upper(c."RegAddress_PostCode") from '^[A-Z]{1,2}')
WHERE c."CompanyNumber" = f.company_number;

\echo '--- firm_master rows with a region (live firms) ---'
SELECT coalesce(region,'(no postcode / dead firm)') AS region, count(*) FROM firm_master GROUP BY 1 ORDER BY 2 DESC;
