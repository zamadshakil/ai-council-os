export interface IntegrationSetupStep {
  title: string;
  detail: string;
  url?: string;
  linkLabel?: string;
}

export interface IntegrationFieldGuide {
  where: string;
  example?: string;
  note?: string;
}

export interface IntegrationSetupGuide {
  summary: string;
  time: string;
  prerequisites: string[];
  steps: IntegrationSetupStep[];
  fields: Record<string, IntegrationFieldGuide>;
  advancedFields?: string[];
  warning?: string;
}

const platformUrl = (url: string, label = 'Open official setup page') => ({ url, linkLabel: label });

export const INTEGRATION_GUIDES: Record<string, IntegrationSetupGuide> = {
  openrouter: {
    summary: 'One key powers all three councils. Add credits first, then create a separate key for Council OS so its spend can be limited and rotated safely.',
    time: 'About 3 minutes',
    prerequisites: ['An OpenRouter account', 'A small positive credit balance'],
    steps: [
      { title: 'Open API Keys', detail: 'Sign in to OpenRouter and open the Keys page.', ...platformUrl('https://openrouter.ai/settings/keys') },
      { title: 'Create a dedicated key', detail: 'Name it “Council OS Production”. Add a monthly spending limit if desired. This must be a normal API key, not a Management API key.' },
      { title: 'Copy, save, and verify', detail: 'Copy the key when it is shown, paste it under Credentials, save it, then use Verify connection.' },
    ],
    fields: {
      api_key: { where: 'OpenRouter → Settings → API Keys → Create Key.', example: 'Starts with sk-or-v1-', note: 'The full key is shown once. Never paste a Management API key here.' },
    },
  },
  telegram: {
    summary: 'Creates one private administrator channel for alerts, approvals, pause commands, and the kill switch.',
    time: 'About 5 minutes',
    prerequisites: ['A Telegram account', 'Telegram mobile or desktop app'],
    steps: [
      { title: 'Create the bot', detail: 'Open the verified @BotFather chat, send /newbot, and follow its name and username prompts.', ...platformUrl('https://t.me/BotFather', 'Open @BotFather') },
      { title: 'Start a private chat', detail: 'Open your new bot and press Start. Council OS deliberately accepts exactly one private administrator chat.' },
      { title: 'Find your numeric chat ID', detail: 'Send any message to the bot, then open the getUpdates link described below. Copy message.chat.id—not the bot username.' },
      { title: 'Save and verify', detail: 'Paste the bot token and numeric chat ID. The webhook secret is optional and only needed if webhook delivery is enabled later.' },
    ],
    fields: {
      bot_token: { where: '@BotFather sends it immediately after /newbot succeeds.', example: '123456789:AA…', note: 'If exposed, revoke it in BotFather and create a replacement.' },
      admin_chat_id: { where: 'After messaging the bot, open https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates and read result[].message.chat.id.', example: 'A numeric value such as 123456789', note: 'Use your private chat ID, not a group ID or @username.' },
      webhook_secret: { where: 'Create your own long random value; Telegram does not issue it.', example: 'At least 32 random characters', note: 'Optional. Leave blank for polling mode.' },
    },
    advancedFields: ['webhook_secret'],
  },
  youtube: {
    summary: 'Read operations can use an API key, but replying to comments or updating descriptions requires OAuth authorization from the channel owner.',
    time: 'About 15–25 minutes',
    prerequisites: ['A Google Cloud project', 'Owner or manager access to the YouTube channel'],
    steps: [
      { title: 'Enable YouTube Data API v3', detail: 'In Google Cloud Console, select a project, open APIs & Services → Library, and enable YouTube Data API v3.', ...platformUrl('https://console.cloud.google.com/apis/library/youtube.googleapis.com') },
      { title: 'Create API credentials', detail: 'Under APIs & Services → Credentials, create an API key for read/quota operations and an OAuth client for the channel owner.' },
      { title: 'Authorize the channel', detail: 'Complete Google OAuth with the YouTube account. Service accounts do not work with YouTube. Export the resulting authorized-user token JSON.' },
      { title: 'Copy the channel ID', detail: 'In YouTube Studio open Settings → Channel → Advanced settings, or copy the channel id returned by channels.list(mine=true).' },
      { title: 'Save and verify', detail: 'Paste the channel ID and OAuth token JSON. Add the API key if available. Verification checks real channel access.' },
    ],
    fields: {
      channel_id: { where: 'YouTube Studio → Settings → Channel → Advanced settings.', example: 'Starts with UC and is normally 24 characters', note: 'This is not the @handle or channel URL slug.' },
      api_key: { where: 'Google Cloud Console → APIs & Services → Credentials → Create credentials → API key.', example: 'Starts with AIza', note: 'Optional for the vault, but useful for read-only quota operations.' },
      oauth_token_json: { where: 'Generated after the channel owner completes Google OAuth using your OAuth client.', example: '{"token":"…","refresh_token":"…","client_id":"…"}', note: 'Paste the complete JSON object, not only the access token. Access tokens expire; the refresh token enables durable automation.' },
      webhook_secret: { where: 'Create your own random secret for signed webhook handling.', example: 'At least 32 random characters', note: 'Optional; leave blank unless webhook delivery is configured.' },
    },
    advancedFields: ['api_key', 'webhook_secret'],
    warning: 'Google does not provide a permanent YouTube “API key” that can publish. Publishing always requires the channel owner’s OAuth consent.',
  },
  reddit: {
    summary: 'Scans approved communities and stages Sales Council replies. Council OS never posts Reddit replies automatically.',
    time: 'About 10 minutes plus Reddit approval',
    prerequisites: ['A Reddit account in good standing', 'Approved access for an external API application'],
    steps: [
      { title: 'Review Reddit API access policy', detail: 'External clients may require registration/approval. Devvit credentials are not interchangeable with this external worker.', ...platformUrl('https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy') },
      { title: 'Register the external application', detail: 'Create an approved script/web application for this single-account read workflow. Record the client ID and secret.' },
      { title: 'Choose a clear user agent', detail: 'Use a descriptive value containing the app, version, and operator—not a browser-like generic string.' },
      { title: 'Save and verify', detail: 'Verification performs a small authenticated read. Replies remain manual-ready after approval.' },
    ],
    fields: {
      client_id: { where: 'Your approved Reddit application’s credential page; it is the short identifier displayed under the app name.', example: 'A short alphanumeric identifier' },
      client_secret: { where: 'The same Reddit application credential page, next to “secret”.', example: 'A longer private value', note: 'Do not use a Devvit app token.' },
      user_agent: { where: 'You choose this value.', example: 'windows:CouncilOS:1.0 (by /u/yourusername)', note: 'Identify the application and operator clearly.' },
    },
    warning: 'Reddit controls external API eligibility. If app registration is unavailable or rejected, Council OS cannot bypass that restriction.',
  },
  x: {
    summary: 'Publishes an approved X variant through a developer App with user-context write permission.',
    time: 'About 10–20 minutes',
    prerequisites: ['An X developer account and Project/App', 'An API plan that permits posting'],
    steps: [
      { title: 'Create or open an App', detail: 'In the X Developer Portal, open Projects & Apps and select the App Council OS will use.', ...platformUrl('https://developer.x.com/en/portal/dashboard') },
      { title: 'Enable write permission', detail: 'In App settings set User authentication to Read and write. Save this before generating user access tokens.' },
      { title: 'Generate Keys and Tokens', detail: 'Open the App’s Keys and tokens tab. Copy API Key/Secret and generate Access Token/Secret after write access is enabled.' },
      { title: 'Save and verify', detail: 'Paste the four required OAuth 1.0a values. Bearer token is optional for current publishing.' },
    ],
    fields: {
      api_key: { where: 'X Developer Portal → your App → Keys and tokens → Consumer Keys → API Key.' },
      api_secret: { where: 'X Developer Portal → your App → Keys and tokens → Consumer Keys → API Key Secret.' },
      access_token: { where: 'X Developer Portal → your App → Keys and tokens → Authentication Tokens → Access Token.' },
      access_secret: { where: 'Generated alongside the Access Token.', note: 'Regenerate both after changing app permissions.' },
      bearer_token: { where: 'X Developer Portal → your App → Keys and tokens → Bearer Token.', note: 'Optional for the current user-context publishing path.' },
    },
    advancedFields: ['bearer_token'],
    warning: 'X plan capabilities and usage charges change independently of Council OS. A valid key can still be blocked if the plan does not include post creation.',
  },
  linkedin: {
    summary: 'Publishes approved content either as the authorized member or as an organization Page the member administers.',
    time: 'About 15–30 minutes',
    prerequisites: ['A LinkedIn Developer App', 'Approved LinkedIn products/scopes', 'Page admin access for organization posting'],
    steps: [
      { title: 'Create/open a LinkedIn App', detail: 'Open the Developer Portal, choose the app, and associate it with the correct Company Page.', ...platformUrl('https://www.linkedin.com/developers/apps') },
      { title: 'Request publishing products', detail: 'Enable the product/access required for member or organization posting. Availability is controlled by LinkedIn.' },
      { title: 'Authorize with OAuth 2.0', detail: 'Generate a 3-legged OAuth access token with the approved posting scope. LinkedIn access tokens expire and must be renewed.' },
      { title: 'Choose the publishing identity', detail: 'Enter Person ID for member publishing or Organization ID for Page publishing. Do not enter the full urn:li: prefix.' },
      { title: 'Save and verify', detail: 'Verification checks that the token can read the selected publishing identity.' },
    ],
    fields: {
      access_token: { where: 'Generated by the LinkedIn OAuth 2.0 authorization flow for your App.', note: 'It is not the Client Secret. Renew it before expiry.' },
      person_id: { where: 'Call LinkedIn /v2/me with the same access token and copy the returned id.', example: 'A context-specific member ID without urn:li:person:' },
      organization_id: { where: 'Open the Company Page; use the numeric ID from the Page/admin URL or organization API response.', example: 'A numeric ID without urn:li:organization:', note: 'Use either Person ID or Organization ID according to where posts should publish.' },
    },
    warning: 'LinkedIn does not grant every app social publishing access automatically. Verification cannot overcome a missing product approval or scope.',
  },
  meta: {
    summary: 'Connects one Facebook Page and its linked professional Instagram account for approved publishing and Instagram comment automation.',
    time: 'About 20–35 minutes',
    prerequisites: ['A Meta Developer App', 'Facebook Page admin access', 'Instagram Professional account linked to that Page'],
    steps: [
      { title: 'Create/open a Meta App', detail: 'In Meta for Developers, create a Business app or open the existing app and add the required Facebook/Instagram products.', ...platformUrl('https://developers.facebook.com/apps/') },
      { title: 'Configure permissions', detail: 'Request only the Page and Instagram permissions needed for publishing, comment management, and account discovery.' },
      { title: 'Generate the proper token', detail: 'Authorize a Page admin, exchange for a long-lived user token where supported, then obtain the Page access token for the selected Page.' },
      { title: 'Discover Page and Instagram IDs', detail: 'Use the Graph API /me/accounts response for the Page ID and query the Page’s instagram_business_account for the Instagram ID.' },
      { title: 'Save and verify', detail: 'Paste the required values. Webhook and API-version fields are under Advanced settings.' },
    ],
    fields: {
      access_token: { where: 'Meta Graph API authorization for the Page administrator; use the Page-capable token required by the selected action.', note: 'A short-lived Graph API Explorer token is unsuitable for unattended production use.' },
      app_id: { where: 'Meta for Developers → My Apps → your App → App settings → Basic.' },
      app_secret: { where: 'Meta for Developers → your App → App settings → Basic → App secret → Show.', note: 'Treat this as a password.' },
      facebook_page_id: { where: 'Graph API /me/accounts or the Page’s About/Page transparency information.', example: 'Numeric Page ID' },
      instagram_business_id: { where: 'Graph API: /<PAGE_ID>?fields=instagram_business_account, then copy instagram_business_account.id.', example: 'Numeric professional Instagram account ID', note: 'A personal Instagram account will not return this ID.' },
      webhook_verify_token: { where: 'Create your own random phrase and use the exact same value in Meta webhook configuration.', note: 'Meta does not generate this value.' },
      api_version: { where: 'Use the version supported by the deployed integration; only override it when Council OS release notes instruct you.', example: 'v23.0' },
    },
    advancedFields: ['app_id', 'facebook_page_id', 'instagram_business_id', 'webhook_verify_token', 'api_version'],
  },
  runpod: {
    summary: 'Lets Council OS create and control the approved one-GPU Blender/Kasm workstation. Council OS generates the agent token, Kasm password, ports, and workspace defaults for you.',
    time: 'About 3 minutes before paid pod creation',
    prerequisites: ['A RunPod account with billing enabled'],
    steps: [
      { title: 'Create an API key', detail: 'In RunPod Console open Settings → API Keys, create a dedicated key, and copy it.', ...platformUrl('https://www.runpod.io/console/user/settings') },
      { title: 'Save and verify', detail: 'Only paste the RunPod API key. Council OS generates all Blender agent and Kasm secrets securely.' },
      { title: 'Create the safe workstation', detail: 'After verification, go to Blender Manager, accept the billing notice, and create the one-A6000 baseline.' },
      { title: 'Stop billing when finished', detail: 'Use Stop billing in Blender Manager. Persistent /workspace storage can continue to incur storage charges while the Pod is stopped.' },
    ],
    fields: {
      api_key: { where: 'RunPod Console → Settings → API Keys → Create API Key.', note: 'This is the only value you supply. Do not paste an endpoint ID or Pod ID.' },
    },
    warning: 'Saving a key does not start a Pod. GPU billing begins only when you explicitly create or resume a workstation.',
  },
  discord: {
    summary: 'Posts each approved Discord variant into one chosen server channel using an incoming webhook. No bot account is required.',
    time: 'About 3 minutes',
    prerequisites: ['Manage Webhooks permission in the Discord server/channel'],
    steps: [
      { title: 'Open channel integrations', detail: 'In Discord, right-click the destination channel → Edit Channel → Integrations → Webhooks.' },
      { title: 'Create the webhook', detail: 'Choose New Webhook, name it Council OS, confirm the destination channel, then choose Copy Webhook URL.' },
      { title: 'Save and verify', detail: 'Paste the complete URL. Verification reads the webhook metadata without posting a message.', ...platformUrl('https://docs.discord.com/developers/platform/webhooks', 'Read Discord’s webhook guide') },
    ],
    fields: {
      webhook_url: { where: 'Discord channel → Edit Channel → Integrations → Webhooks → Copy Webhook URL.', example: 'https://discord.com/api/webhooks/<id>/<token>', note: 'The URL contains a secret token. Anyone with it can post to that channel.' },
    },
  },
  hubspot: {
    summary: 'Adds or updates an approved Sales Council lead in HubSpot Contacts and attaches the approved outreach as an audited note.',
    time: 'About 5 minutes',
    prerequisites: ['HubSpot Super Admin or Developer Tools access'],
    steps: [
      { title: 'Open Service Keys', detail: 'In HubSpot use Settings → Integrations → Service Keys, or Development → Keys → Service Keys.', ...platformUrl('https://developers.hubspot.com/changelog/service-keys', 'Read HubSpot’s official Service Key guide') },
      { title: 'Create the key', detail: 'Name it “Council OS approved sales sync”. You do not need a legacy app, Personal Access Key, webhook, or OAuth app.' },
      { title: 'Grant only two scopes', detail: 'Add crm.objects.contacts.read and crm.objects.contacts.write. Council OS does not need broad CMS, deals, or account scopes.' },
      { title: 'Copy, save, and verify', detail: 'Copy the Service Key once, paste it here, save, then verify. Link it to Sales Council only after verification succeeds.' },
    ],
    fields: {
      access_token: { where: 'HubSpot → Settings → Integrations → Service Keys → Create a service key.', example: 'The Service Key shown after creation', note: 'Do not use the Personal Access Key—it authenticates HubSpot developer tooling, not this CRM sync.' },
    },
    warning: 'If verification returns 403, edit the Service Key and add both Contacts read and Contacts write permissions. Do not add unrelated scopes.',
  },
};
