// SMTP settings for common email providers, so most people only enter an email address and an
// app password. Checked November 2026; providers change these rarely.

/** Known providers. `blocked` explains why one cannot be used yet. */
export const MAIL_PROVIDERS = [
  {
    id: 'gmail',
    name: 'Gmail or Google Workspace',
    domains: ['gmail.com', 'googlemail.com'],
    host: 'smtp.gmail.com',
    port: 587,
    mode: 'starttls',
    steps: [
      'Turn on 2-Step Verification for your Google account.',
      "Open Google's App passwords page and create one called Nära Hem.",
      'Paste the 16-letter app password below. Your normal Gmail password will not work.',
    ],
    link: { label: 'Open Google App passwords', url: 'https://myaccount.google.com/apppasswords' },
    passwordHint: 'Gmail needs an app password, not your normal Gmail password.',
  },
  {
    id: 'icloud',
    name: 'iCloud Mail',
    domains: ['icloud.com', 'me.com', 'mac.com'],
    host: 'smtp.mail.me.com',
    port: 587,
    mode: 'starttls',
    steps: [
      'Sign in to your Apple Account and open Sign-In and Security.',
      'Choose App-Specific Passwords and create one called Nära Hem.',
      'Paste it below. Your normal Apple Account password will not work.',
    ],
    link: { label: 'Open Apple Account', url: 'https://account.apple.com' },
    passwordHint: 'iCloud needs an app-specific password, not your Apple Account password.',
  },
  {
    id: 'yahoo',
    name: 'Yahoo Mail',
    domains: ['yahoo.com', 'ymail.com', 'rocketmail.com'],
    host: 'smtp.mail.yahoo.com',
    port: 465,
    mode: 'tls',
    steps: [
      'Open Yahoo Account Security.',
      'Choose Generate app password and name it Nära Hem.',
      'Paste it below. Your normal Yahoo password will not work.',
    ],
    link: { label: 'Open Yahoo Account Security', url: 'https://login.yahoo.com/account/security' },
    passwordHint: 'Yahoo needs an app password, not your normal Yahoo password.',
  },
  {
    id: 'fastmail',
    name: 'Fastmail',
    domains: ['fastmail.com', 'fastmail.fm'],
    host: 'smtp.fastmail.com',
    port: 465,
    mode: 'tls',
    steps: [
      'In Fastmail, open Settings → Privacy & Security → App passwords.',
      'Create a new app password with SMTP access and name it Nära Hem.',
      'Paste it below.',
    ],
    passwordHint: 'Fastmail needs an app password with SMTP access.',
  },
  {
    id: 'microsoft365',
    name: 'Microsoft 365 (work or school)',
    domains: [],
    host: 'smtp.office365.com',
    port: 587,
    mode: 'starttls',
    steps: [
      'Use your work or school email address and password.',
      'Your administrator must allow SMTP sign-in for your mailbox, or it will be rejected.',
      'Microsoft plans to turn this off by default after the end of 2026.',
    ],
    passwordHint: 'Ask your Microsoft 365 administrator to allow SMTP sign-in for this mailbox.',
  },
  {
    id: 'outlook',
    name: 'Outlook.com or Hotmail',
    domains: ['outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'passport.com'],
    blocked:
      'Microsoft no longer lets apps send from personal Outlook.com or Hotmail accounts with a ' +
      'password, and Nära Hem cannot use its sign-in method yet. Use another account, such as ' +
      'Gmail or iCloud, for your server email.',
  },
  {
    id: 'other',
    name: 'Other',
    domains: [],
    steps: ["Enter your provider's SMTP server details under Advanced."],
  },
];

/** Returns a provider by id, or Other. */
export function mailProvider(id) {
  return MAIL_PROVIDERS.find((p) => p.id === id) ?? MAIL_PROVIDERS.at(-1);
}

/** Guesses the provider from an email address, or returns Other. */
export function providerForEmail(email) {
  const domain = String(email).split('@')[1]?.trim().toLowerCase() ?? '';
  return MAIL_PROVIDERS.find((p) => p.domains.includes(domain)) ?? mailProvider('other');
}

/** Finds the provider that saved settings belong to, by server name, or returns Other. */
export function providerForHost(host) {
  const name = String(host).trim().toLowerCase();
  return MAIL_PROVIDERS.find((p) => p.host === name) ?? mailProvider('other');
}
