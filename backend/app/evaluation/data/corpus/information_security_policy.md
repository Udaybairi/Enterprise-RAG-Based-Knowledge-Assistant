# Information Security Policy

## Passwords and Authentication
All passwords must be at least 16 characters long and must not be reused across systems.
Multi-factor authentication (MFA) is mandatory for email, VPN, source code repositories and all production systems.
Hardware security keys are required for administrators of production infrastructure.

## Data Classification
Northwind classifies information into four levels: Public, Internal, Confidential and Restricted.
Restricted data, such as customer payment information and health records, must be encrypted at rest using AES-256 and may only be stored in approved systems.
Confidential documents must not be shared with external parties without a signed non-disclosure agreement.

## Incident Reporting
Suspected security incidents must be reported to the Security Operations Center within 30 minutes by calling the hotline or emailing soc@northwind.example.
Lost or stolen laptops and phones must be reported immediately so they can be remotely wiped.
The SOC classifies incidents from SEV1 (critical) to SEV4 (low); SEV1 incidents trigger the on-call incident commander.

## Device Security
Company laptops use full-disk encryption and must lock automatically after 5 minutes of inactivity.
Personal devices may only access company email through the managed mobile application.
