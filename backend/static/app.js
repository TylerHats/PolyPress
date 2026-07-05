        function compileBlocksToHtml(blocks, customFooterHtml = null, isFooterMode = false) {
            let rowsHtml = '';
            for (let block of blocks) {
                if (block.type === 'heading') {
                    rowsHtml += `
                    <tr>
                        <td align="${block.align || 'center'}" style="padding: ${block.padding || '10px 0'};">
                            <h1 style="margin: 0; font-family: sans-serif; font-size: ${block.size || '28px'}; color: ${block.color || '#111827'}; font-weight: bold; line-height: 1.3;">
                                ${block.text}
                            </h1>
                        </td>
                    </tr>`;
                } else if (block.type === 'paragraph') {
                    rowsHtml += `
                    <tr>
                        <td align="${block.align || 'left'}" style="padding: ${block.padding || '10px 0'};">
                            <p style="margin: 0; font-family: sans-serif; font-size: ${block.size || '16px'}; color: ${block.color || '#374151'}; line-height: 1.6;">
                                ${block.text.replace(/\n/g, '<br>')}
                            </p>
                        </td>
                    </tr>`;
                } else if (block.type === 'button') {
                    rowsHtml += `
                    <tr>
                        <td align="${block.align || 'center'}" style="padding: 15px 0;">
                            <table border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto; border-collapse: separate;">
                                <tr>
                                    <td align="center" bgcolor="${block.bg_color || '#4f46e5'}" style="border-radius: ${block.border_radius || '6px'};">
                                        <a href="${block.url || '#'}" target="_blank" style="display: inline-block; padding: ${block.padding || '12px 24px'}; font-family: sans-serif; font-size: 15px; font-weight: bold; color: ${block.text_color || '#ffffff'}; text-decoration: none; border-radius: ${block.border_radius || '6px'};">
                                            ${block.text}
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>`;
                } else if (block.type === 'image') {
                    rowsHtml += `
                    <tr>
                        <td align="center" style="padding: ${block.padding || '10px 0'};">
                            <img src="${block.url || 'https://picsum.photos/600/300'}" alt="${block.alt || 'Image'}" style="display: block; width: 100%; max-width: 600px; height: auto; border: 0; border-radius: ${block.border_radius || '0px'};" />
                        </td>
                    </tr>`;
                } else if (block.type === 'columns') {
                    let leftPct = '48%';
                    let rightPct = '48%';
                    let gapPct = '4%';
                    if (block.layout === '70-30') {
                        leftPct = '68%';
                        rightPct = '28%';
                        gapPct = '4%';
                    } else if (block.layout === '30-70') {
                        leftPct = '28%';
                        rightPct = '68%';
                        gapPct = '4%';
                    }
                    
                    let leftHtml = '';
                    if (block.left.type === 'paragraph') {
                        leftHtml = `<div style="text-align: ${block.left.align || 'left'}; color: ${block.left.color || '#334155'}; font-family: sans-serif; font-size: ${block.left.size || '15px'}; line-height: 1.5;">${block.left.text}</div>`;
                    } else if (block.left.type === 'heading') {
                        leftHtml = `<h3 style="text-align: ${block.left.align || 'center'}; color: ${block.left.color || '#1e293b'}; font-family: sans-serif; font-size: ${block.left.size || '22px'}; margin: 0 0 10px 0;">${block.left.text}</h3>`;
                    } else if (block.left.type === 'image') {
                        leftHtml = `<img src="${block.left.url || 'https://picsum.photos/300/150'}" alt="${block.left.alt || ''}" style="display: block; width: 100%; height: auto; border: 0; border-radius: 4px;" />`;
                    } else if (block.left.type === 'button') {
                        leftHtml = `
                        <table border="0" cellpadding="0" cellspacing="0" align="${block.left.align || 'center'}">
                            <tr>
                                <td align="center" bgcolor="${block.left.bg_color || '#4f46e5'}" style="border-radius: 4px;">
                                    <a href="${block.left.url || '#'}" target="_blank" style="display: inline-block; padding: 8px 16px; font-family: sans-serif; font-size: 13px; font-weight: bold; color: ${block.left.text_color || '#ffffff'}; text-decoration: none; border-radius: 4px;">
                                        ${block.left.text}
                                    </a>
                                </td>
                            </tr>
                        </table>`;
                    }
                    
                    let rightHtml = '';
                    if (block.right.type === 'paragraph') {
                        rightHtml = `<div style="text-align: ${block.right.align || 'left'}; color: ${block.right.color || '#334155'}; font-family: sans-serif; font-size: ${block.right.size || '15px'}; line-height: 1.5;">${block.right.text}</div>`;
                    } else if (block.right.type === 'heading') {
                        rightHtml = `<h3 style="text-align: ${block.right.align || 'center'}; color: ${block.right.color || '#1e293b'}; font-family: sans-serif; font-size: ${block.right.size || '22px'}; margin: 0 0 10px 0;">${block.right.text}</h3>`;
                    } else if (block.right.type === 'image') {
                        rightHtml = `<img src="${block.right.url || 'https://picsum.photos/300/150'}" alt="${block.right.alt || ''}" style="display: block; width: 100%; height: auto; border: 0; border-radius: 4px;" />`;
                    } else if (block.right.type === 'button') {
                        rightHtml = `
                        <table border="0" cellpadding="0" cellspacing="0" align="${block.right.align || 'center'}">
                            <tr>
                                <td align="center" bgcolor="${block.right.bg_color || '#4f46e5'}" style="border-radius: 4px;">
                                    <a href="${block.right.url || '#'}" target="_blank" style="display: inline-block; padding: 8px 16px; font-family: sans-serif; font-size: 13px; font-weight: bold; color: ${block.right.text_color || '#ffffff'}; text-decoration: none; border-radius: 4px;">
                                        ${block.right.text}
                                    </a>
                                </td>
                            </tr>
                        </table>`;
                    }
                    
                    rowsHtml += `
                    <tr>
                        <td style="padding: 15px 0;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td width="${leftPct}" valign="${block.left.valign || 'top'}">
                                        ${leftHtml}
                                    </td>
                                    <td width="${gapPct}">&nbsp;</td>
                                    <td width="${rightPct}" valign="${block.right.valign || 'top'}">
                                        ${rightHtml}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>`;
                } else if (block.type === 'divider') {
                    rowsHtml += `
                    <tr>
                        <td style="padding: ${block.padding || '20px 0'};">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td height="${block.height || '1px'}" bgcolor="${block.color || '#e5e7eb'}" style="font-size: 1px; line-height: 1px;">&nbsp;</td>
                                </tr>
                            </table>
                        </td>
                    </tr>`;
                } else if (block.type === 'spacer') {
                    rowsHtml += `
                    <tr>
                        <td height="${block.height || '20px'}" style="font-size: 1px; line-height: 1px;">&nbsp;</td>
                    </tr>`;
                }
            }
            
            if (isFooterMode) {
                return rowsHtml;
            }
            
            let footerSegment = `
                                 <tr>
                                     <td style="padding-top: 40px;">
                                         <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                             <tr>
                                                 <td height="1" bgcolor="#e5e7eb" style="font-size:1px; line-height:1px;">&nbsp;</td>
                                             </tr>
                                             <tr>
                                                 <td align="center" style="padding-top: 20px; font-family: sans-serif; font-size: 12px; color: #9ca3af; line-height: 1.5;">
                                                     You are receiving this email because you subscribed to our newsletter list.<br>
                                                     <a href="{{unsubscribe_url}}" style="color: #6366f1; text-decoration: underline;">Unsubscribe</a> from this list.
                                                 </td>
                                             </tr>
                                         </table>
                                     </td>
                                 </tr>`;
                                 
            if (customFooterHtml) {
                footerSegment = `
                                 <tr>
                                     <td style="padding-top: 40px;">
                                         <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                             <tr>
                                                 <td height="1" bgcolor="#e5e7eb" style="font-size:1px; line-height:1px;">&nbsp;</td>
                                             </tr>
                                             ${customFooterHtml}
                                         </table>
                                     </td>
                                 </tr>`;
            }
            
            return `<!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Newsletter</title>
                <style>
                    body { margin: 0; padding: 0; background-color: #f3f4f6; -webkit-font-smoothing: antialiased; }
                    img { max-width: 100%; height: auto; display: block; border: 0; }
                </style>
            </head>
            <body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: sans-serif;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" bgcolor="#f3f4f6" style="table-layout: fixed;">
                    <tr>
                        <td align="center" style="padding: 40px 10px;">
                            <!--[if mso]>
                            <table align="center" border="0" cellspacing="0" cellpadding="0" width="600">
                            <tr>
                            <td align="center" valign="top" width="600">
                            <![endif]-->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); padding: 40px;">
                                ${rowsHtml}
                                ${footerSegment}
                            </table>
                            <!--[if mso]>
                            </td>
                            </tr>
                            </table>
                            <![endif]-->
                        </td>
                    </tr>
                </table>
            </body>
            </html>`;
        }

        function polyPressApp() {
            return {
                authenticated: false,
                activeTab: 'dashboard',
                
                confirmModal: {
                    open: false,
                    title: '',
                    message: '',
                    isPrompt: false,
                    isDanger: false,
                    inputValue: '',
                    inputPlaceholder: '',
                    cancelText: 'Cancel',
                    confirmText: 'Confirm',
                    resolve: null
                },
                token: null,
                draggedIndex: null,
                toasts: [],
                dashboardChart: null,
                
                // Onboarding & 2FA controls
                setupCompleted: true,
                setupForm: {
                    app_name: 'PolyPress',
                    tenant_name: '',
                    public_url: '',
                    admin_name: 'System Administrator',
                    admin_email: '',
                    admin_password: '',
                    direct_send: false,
                    mta_from_prefix: 'noreply',
                    dkim_domain: '',
                    dkim_selector: 'polypress',
                    smtp_host: '',
                    smtp_port: 587,
                    smtp_username: '',
                    smtp_password: '',
                    smtp_use_ssl: false,
                    smtp_use_tls: true,
                    imap_host: '',
                    imap_port: 993,
                    imap_username: '',
                    imap_password: '',
                    imap_use_ssl: true
                },
                totpRequired: false,
                totpForm: { email: '', code: '' },
                totpSetup: { secret: '', uri: '', code: '', step: 1 },
                dnsTestResults: {
                    mx: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                    spf: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] }, spf_warning: '' },
                    dkim: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                    dmarc: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                    ptr: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                    blacklist: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } }
                },
                dnsTesting: false,
                detectedPublicIp: '',
                outboxQueue: [],
                mockPreviewFields: { name: 'John Doe', email: 'john@example.com' },
                previewIframeSrc: '',

                // Form payloads
                loginForm: { email: '', password: '' },
                campaignForm: { name: '', subject: '', list_id: '', list_ids: [] },
                listForm: { name: '', description: '' },
                tenantForm: { id: null, name: '', generate_dkim: true },
                subscriberForm: { id: null, email: '', name: '', status: 'active', tags: '', custom_data: {} },
                launchScheduling: { enabled: false, date: '', timezone: 'UTC' },
                embedCodeTheme: 'dark',
                
                // Host admin & user management state
                hostAdminMode: true,
                activeTenantId: localStorage.getItem('polypress_active_tenant') || null,
                usersList: [],
                userForm: { id: null, email: '', name: '', password: '', role: 'tenant_user', tenant_id: null, allowed_tenants: [] },
                userModalOpen: false,
                profileModalOpen: false,
                profileForm: { name: '', password: '' },
                
                // Session details
                loadingSession: true,
                user: { id: null, email: '', name: '', role: '', tenant_id: null, totp_enabled: false },
                tenant: { id: null, name: '', direct_send: false, mta_from_prefix: 'noreply', speed_emails_per_hour: 500 },
                globalSettings: { app_name: '', public_url: '', oidc_enabled: false, local_login_enabled: true, auto_update: false, update_channel: 'stable', backup_token: '', external_backup_url: '', external_backup_auth_header: '' },
                updateStatus: { current_commit: '', current_tag: '', latest_commit: '', latest_tag: '', update_available: false, update_channel: 'stable', auto_update: false, is_systemd: false, is_docker: false },
                schemaMismatch: { active: false, code_ver: 0, db_ver: 0 },
                schemaBypassForm: { email: '', password: '' },
                schemaBypassing: false,
                updateChecking: false,
                updateInstalling: false,
                smtpTestEmail: '',
                testingSmtp: false,
                testingImap: false,
                isEditingOptIn: false,
                isEditingFooter: false,
                optInSubject: 'Confirm Your Subscription',
                loadingDashboardStats: false,
                sslForm: { domain: '', email: '', use_staging: true },
                sslStatus: { configured: false, expiry: '', issuer: '', subject: '' },
                acmeLogs: [],
                sslGenerating: false,
                apiKeys: [],
                webhooks: [],
                newlyCreatedKey: '',
                webhookForm: { url: '', events_str: '*' },
                
                // Content lists
                campaigns: [],
                lists: [],
                tenants: [],
                backups: [],
                
                // Modals
                modals: {
                    createCampaign: false,
                    createList: false,
                    editFields: false,
                    embedCode: false,
                    addSubscriber: false,
                    createTenant: false,
                    csvImport: false,
                    confirmLaunch: false,
                    stats: false,
                    campaignPreview: false,
                    createWebhook: false,
                    targetPreview: false,
                    dnsDetails: false,
                    insertLink: false
                },
                linkForm: { text: '', url: 'https://' },
                lastFocusedInput: { id: '', selectionStart: 0, selectionEnd: 0 },
                dnsDetailRecord: null,
                targetPreviewData: [],
                targetPreviewTotal: 0,
                targetPreviewPage: 1,
                targetPreviewFilter: { search: '', status: '' },
                
                // Subscriber sub list bindings
                listSelected: null,
                listSelectedName: '',
                listSelectedFields: [],
                subscribers: [],
                subscribersCount: 0,
                subscribersPage: 1,
                subscribersSearch: '',
                subscribersFilterStatus: '',
                subscribersFilterEngagement: '',
                subscribersFilterTag: '',

                // Custom fields mapping
                fieldsListTarget: { name: '', custom_fields: [], form_settings: { name_required: false } },
                newField: { label: '', key: '' },
                
                // Embed code helpers
                embedCodeTag: 'Website',
                embedCodeString: '',
                embedIframeSrc: '',
                
                // CSV upload state
                csvListTarget: { name: '', custom_fields: [] },
                csvFile: null,
                csvHeaders: [],
                csvMapping: { email: '', name: '', custom_fields: {} },
                csvImportStep: 1,
                
                // Visual block editor state
                editingCampaign: { id: null, name: '', subject: '', target_rules: { tag: '', engagement: [], signup_after: '', signup_before: '' } },
                targetingCollapsed: true,
                editorBlocks: [],
                selectedBlockIndex: null,
                
                // Stats popup
                campaignStats: { name: '', sent: 0, opens: 0, clicks: 0, bounces: 0, click_stats: [] },
                showClickMapVisualizer: false,
                clickMapHtml: '',
                clickMapStats: [],
                
                // Dashboard summary
                stats: { totalSubscribers: 0, campaignsSent: 0, avgOpenRate: 0, avgBounceRate: 0 },
                
                // Pre-fetched sub-templates
                templates: {},
                
                // Custom logo versioning
                logoVersion: Date.now(),
                logoFileName: '',
                
                // Chart timeout identifier
                chartTimeoutId: null,
                
                // Historical Reports state
                reportsData: [],
                reportsFilterStartDate: '',
                reportsFilterEndDate: '',
                reportsSettings: { retention_days: 30, frequency_hours: 24 },
                reportsChart: null,
                reportsChartTimeoutId: null,
                reportsTimezone: 'local',
                dashboardPeriod: 30,
                trends: {
                    subscribers: { diff: 0 },
                    campaigns: { diff: 0 },
                    openRate: { diff: 0 },
                    bounceRate: { diff: 0 }
                },

                askConfirm(message, title = 'Confirm Action', isDanger = false) {
                    return new Promise((resolve) => {
                        this.confirmModal.title = title;
                        this.confirmModal.message = message;
                        this.confirmModal.isPrompt = false;
                        this.confirmModal.isDanger = isDanger;
                        this.confirmModal.cancelText = 'Cancel';
                        this.confirmModal.confirmText = 'Confirm';
                        this.confirmModal.resolve = resolve;
                        this.confirmModal.open = true;
                    });
                },
                
                askPrompt(message, placeholder = '', title = 'Enter Value') {
                    return new Promise((resolve) => {
                        this.confirmModal.title = title;
                        this.confirmModal.message = message;
                        this.confirmModal.isPrompt = true;
                        this.confirmModal.inputValue = '';
                        this.confirmModal.inputPlaceholder = placeholder;
                        this.confirmModal.isDanger = false;
                        this.confirmModal.cancelText = 'Cancel';
                        this.confirmModal.confirmText = 'Submit';
                        this.confirmModal.resolve = resolve;
                        this.confirmModal.open = true;
                    });
                },

                refreshIcons() {
                    const run = () => {
                        if (window.lucide) {
                            if (typeof window.lucide.createIcons === 'function') {
                                window.lucide.createIcons();
                            } else if (typeof window.lucide.replace === 'function') {
                                window.lucide.replace();
                            }
                        }
                    };
                    run();
                    setTimeout(run, 50);
                    setTimeout(run, 150);
                    setTimeout(run, 350);
                    setTimeout(run, 700);
                },

                async initApp() {
                    this.loadingSession = true;
                    try {
                        // Pre-fetch sub-templates
                        const templates = ['dashboard', 'campaigns', 'subscribers', 'settings', 'users', 'reports', 'admin'];
                        this.templates = {};
                        for (const t of templates) {
                            try {
                                const res = await fetch(`/static/templates/${t}.html?_t=${Date.now()}`);
                                if (res.ok) {
                                    this.templates[t] = await res.text();
                                }
                            } catch(e) {
                                console.error(`Failed to pre-fetch template ${t}:`, e);
                            }
                        }

                        // Check schema status first
                        try {
                            const statusRes = await fetch('/api/admin/update/schema-status');
                            if (statusRes.ok) {
                                const statusData = await statusRes.json();
                                if (statusData.schema_mismatch) {
                                    this.schemaMismatch.active = true;
                                    this.schemaMismatch.code_ver = statusData.current_code_version;
                                    this.schemaMismatch.db_ver = statusData.db_schema_version;
                                    this.refreshIcons();
                                    return;
                                }
                            }
                        } catch(e) {
                            console.error('Error fetching schema status:', e);
                        }

                        // Check if setup completed
                        try {
                            const statusRes = await fetch('/api/auth/setup/status');
                            const statusData = await statusRes.json();
                            this.setupCompleted = statusData.setup_completed;
                        } catch(e) {
                            this.setupCompleted = true;
                        }

                        this.token = localStorage.getItem('polypress_token');
                        await this.loadGlobalConfig();
                        
                        const urlParams = new URLSearchParams(window.location.search);
                        // Check for OIDC error in URL query params or hash query params
                        let urlError = urlParams.get('error');
                        if (!urlError && window.location.hash.includes('?')) {
                            const hashParams = new URLSearchParams(window.location.hash.split('?')[1]);
                            urlError = hashParams.get('error');
                        }
                        if (urlError) {
                            this.showToast(decodeURIComponent(urlError), 'error');
                            // Clean url
                            let cleanUrl = window.location.pathname;
                            if (window.location.hash) {
                                const hashParts = window.location.hash.split('?');
                                if (hashParts.length > 1) {
                                    const hashParams = new URLSearchParams(hashParts[1]);
                                    hashParams.delete('error');
                                    const remaining = hashParams.toString();
                                    cleanUrl += hashParts[0] + (remaining ? '?' + remaining : '');
                                } else {
                                    cleanUrl += window.location.hash;
                                }
                            } else {
                                const searchParams = new URLSearchParams(window.location.search);
                                searchParams.delete('error');
                                const remaining = searchParams.toString();
                                cleanUrl += remaining ? '?' + remaining : '';
                            }
                            window.history.replaceState({}, document.title, cleanUrl);
                        }

                        // Look for OIDC tokens in URL query params or hash query params
                        let oidcToken = null;
                        if (urlParams.has('token')) {
                            oidcToken = urlParams.get('token');
                        } else {
                            const hash = window.location.hash;
                            if (hash.includes('?')) {
                                const hashParams = new URLSearchParams(hash.split('?')[1]);
                                if (hashParams.has('token')) {
                                    oidcToken = hashParams.get('token');
                                }
                            }
                        }
                        if (oidcToken) {
                            this.token = oidcToken;
                            localStorage.setItem('polypress_token', oidcToken);
                            // Clean url (remove token completely and reset hash to root)
                            let cleanUrl = window.location.pathname;
                            if (window.location.search) {
                                const searchParams = new URLSearchParams(window.location.search);
                                searchParams.delete('token');
                                const remaining = searchParams.toString();
                                if (remaining) {
                                    cleanUrl += '?' + remaining;
                                }
                            }
                            window.history.replaceState({}, document.title, cleanUrl);
                        }
                        
                        if (this.token) {
                            await this.verifySession();
                        }
                    } finally {
                        this.loadingSession = false;
                    }
                },
                
                async submitSetupWizard() {
                    if (!this.setupForm.admin_email || !this.setupForm.admin_password) {
                        this.showToast('Administrator email and password required', 'error');
                        return;
                    }
                    try {
                        const res = await fetch('/api/auth/setup', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.setupForm)
                        });
                        
                        if (!res.ok) {
                            const err = await res.json();
                            throw new Error(err.detail || 'Setup onboarding failed');
                        }
                        
                        const data = await res.json();
                        this.token = data.access_token;
                        localStorage.setItem('polypress_token', this.token);
                        this.setupCompleted = true;
                        await this.verifySession();
                        this.showToast('PolyPress setup completed! Welcome aboard.');
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async loadGlobalConfig() {
                    try {
                        const res = await fetch('/api/auth/public-settings');
                        if (res.ok) {
                            const data = await res.json();
                            this.globalSettings.app_name = data.app_name || 'PolyPress';
                            this.globalSettings.app_logo = data.app_logo;
                            this.globalSettings.oidc_enabled = data.oidc_enabled;
                            this.globalSettings.local_login_enabled = data.local_login_enabled !== undefined ? data.local_login_enabled : true;
                            document.title = this.globalSettings.app_name;
                        }
                    } catch(e) {
                        console.error('Failed to load public settings:', e);
                    }
                },
                
                showToast(message, type = 'success') {
                    const id = Date.now();
                    this.toasts.push({ id, message, type });
                    setTimeout(() => {
                        this.toasts = this.toasts.filter(t => t.id !== id);
                    }, 3000);
                    this.refreshIcons();
                },
                
                async handleLogin() {
                    try {
                        const res = await fetch('/api/auth/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.loginForm)
                        });
                        
                        if (!res.ok) {
                            const err = await res.json();
                            throw new Error(err.detail || 'Authentication failed');
                        }
                        
                        const data = await res.json();
                        if (data.status === 'totp_required') {
                            this.totpRequired = true;
                            this.totpForm.email = data.email;
                            this.totpForm.code = '';
                            this.showToast('2FA verification code required');
                        } else {
                            this.token = data.access_token;
                            localStorage.setItem('polypress_token', this.token);
                            await this.verifySession();
                            this.showToast('Login successful!');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async handleTotpVerify() {
                    try {
                        const res = await fetch('/api/auth/totp-verify', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                email: this.totpForm.email,
                                code: this.totpForm.code
                            })
                        });
                        
                        if (!res.ok) {
                            const err = await res.json();
                            throw new Error(err.detail || 'Invalid 2FA code');
                        }
                        
                        const data = await res.json();
                        this.token = data.access_token;
                        localStorage.setItem('polypress_token', this.token);
                        this.totpRequired = false;
                        await this.verifySession();
                        this.showToast('2FA Verification successful!');
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                async initiateTotpSetup() {
                    try {
                        const res = await fetch('/api/auth/totp/setup', {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        const data = await res.json();
                        this.totpSetup.secret = data.secret;
                        this.totpSetup.uri = data.uri;
                        this.totpSetup.code = '';
                        this.totpSetup.step = 2;
                        
                        // Render QR Code locally offline
                        this.$nextTick(() => {
                            const qrContainer = document.getElementById("totp-qrcode");
                            if (qrContainer) {
                                qrContainer.innerHTML = '';
                                new QRCode(qrContainer, {
                                    text: data.uri,
                                    width: 160,
                                    height: 160,
                                    colorDark: "#0b111e",
                                    colorLight: "#ffffff",
                                    correctLevel: QRCode.CorrectLevel.M
                                });
                            }
                        });
                    } catch(e) {
                        this.showToast('Failed to start 2FA setup', 'error');
                    }
                },
                
                async enableTotp() {
                    try {
                        const res = await fetch('/api/auth/totp/enable', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                secret: this.totpSetup.secret,
                                code: this.totpSetup.code
                            })
                        });
                        if (res.ok) {
                            this.showToast('Two-Factor Authentication is active!');
                            this.user.totp_enabled = true;
                            this.totpSetup.step = 1;
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Invalid verification code');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async disableTotp() {
                    try {
                        const res = await fetch('/api/auth/totp/disable', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                code: this.totpSetup.code
                            })
                        });
                        if (res.ok) {
                            this.showToast('Two-Factor Authentication has been disabled.');
                            this.user.totp_enabled = false;
                            this.totpSetup.code = '';
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Invalid verification code');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async runDnsDiagnostics() {
                    this.dnsTesting = true;
                    try {
                        const res = await fetch('/api/tenants/my/dns-test', {
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.dnsTestResults = await res.json();
                            this.showToast('DNS diagnostics complete');
                        }
                    } catch(e) {
                        this.showToast('DNS diagnostics query failed', 'error');
                    } finally {
                        this.dnsTesting = false;
                    }
                },
                
                async fetchOutboxQueue() {
                    try {
                        const res = await fetch('/api/tenants/my/queue', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.outboxQueue = await res.json();
                        }
                    } catch(e) {}
                },
                
                async purgeQueueItem(id) {
                    if (!await this.askConfirm('Remove this message from the outbound sending queue?', 'Confirm Purging Queue Item', true)) return;
                    try {
                        const res = await fetch(`/api/tenants/my/queue/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Queue item purged');
                            await this.fetchOutboxQueue();
                        }
                    } catch(e) {}
                },
                
                async openPreviewModal() {
                    if (this.isEditingOptIn || this.isEditingFooter) {
                        this.previewIframeSrc = 'about:blank';
                        this.modals.campaignPreview = true;
                        this.refreshIcons();
                        setTimeout(() => {
                            const iframe = document.getElementById('previewIframe');
                            if (iframe) {
                                let html = '';
                                if (this.isEditingFooter) {
                                    html = compileBlocksToHtml(
                                        [
                                            { type: 'heading', text: 'Campaign Content Placeholder', align: 'center', color: '#111827', size: '22px' },
                                            { type: 'paragraph', text: 'This is placeholder campaign content to demonstrate how your customized footer appears at the bottom of outgoing emails.', align: 'center', color: '#4b5563', size: '14px' }
                                        ],
                                        compileBlocksToHtml(this.editorBlocks, null, true)
                                    );
                                } else {
                                    html = compileBlocksToHtml(this.editorBlocks, this.tenant.email_footer_html);
                                }
                                const mockHtml = html.replaceAll('{{confirm_url}}', 'https://newsletter.yourdomain.com/api/embed/confirm-optin/mock_token').replaceAll('{confirm_url}', 'https://newsletter.yourdomain.com/api/embed/confirm-optin/mock_token');
                                const doc = iframe.contentDocument || iframe.contentWindow.document;
                                doc.open();
                                doc.write(mockHtml);
                                doc.close();
                            }
                        }, 150);
                        return;
                    }
                    
                    await this.saveCampaignDraft();
                    this.modals.campaignPreview = true;
                    this.updatePreviewIframe();
                    this.refreshIcons();
                },
                
                updatePreviewIframe() {
                    this.previewIframeSrc = `/api/campaigns/${this.editingCampaign.id}/preview?mock_name=${encodeURIComponent(this.mockPreviewFields.name)}&mock_email=${encodeURIComponent(this.mockPreviewFields.email)}&token=${encodeURIComponent(this.token)}&_t=${Date.now()}`;
                },
                
                async fetchSslStatus() {
                    try {
                        const res = await fetch('/api/ssl/status', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.sslStatus = await res.json();
                        }
                    } catch(e) {}
                },
                
                async generateSslCertificate() {
                    if (!this.sslForm.domain || !this.sslForm.email) {
                        this.showToast('Domain name and email address are required', 'error');
                        return;
                    }
                    
                    this.sslGenerating = true;
                    this.acmeLogs = ['[Console] Starting ACME SSL request...'];
                    
                    let pollInterval = setInterval(async () => {
                        try {
                            const res = await fetch('/api/ssl/logs', { headers: this.getAuthHeaders() });
                            if (res.ok) {
                                this.acmeLogs = await res.json();
                                setTimeout(() => {
                                    const consoleEl = document.getElementById('acme-console');
                                    if (consoleEl) consoleEl.scrollTop = consoleEl.scrollHeight;
                                }, 50);
                            }
                        } catch(e) {}
                    }, 1000);
                    
                    try {
                        const res = await fetch('/api/ssl/generate', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.sslForm)
                        });
                        
                        clearInterval(pollInterval);
                        
                        if (res.ok) {
                            const data = await res.json();
                            this.acmeLogs = data.logs;
                            if (data.status === 'success') {
                                this.showToast('SSL Certificate generated successfully!');
                            } else {
                                this.showToast('SSL Certificate generation failed', 'error');
                            }
                        } else {
                            this.showToast('SSL Request failed', 'error');
                        }
                    } catch(e) {
                        clearInterval(pollInterval);
                        this.showToast(e.message, 'error');
                    } finally {
                        this.sslGenerating = false;
                        await this.fetchSslStatus();
                    }
                },
                
                async fetchDeveloperConsole() {
                    try {
                        const resKeys = await fetch('/api/developer/keys', { headers: this.getAuthHeaders() });
                        if (resKeys.ok) this.apiKeys = await resKeys.json();
                        
                        const resHooks = await fetch('/api/developer/webhooks', { headers: this.getAuthHeaders() });
                        if (resHooks.ok) this.webhooks = await resHooks.json();
                    } catch(e) {}
                },
                
                async generateApiKey() {
                    const name = await this.askPrompt('Enter a label/name for this API Key:', 'landing-page-sync', 'Generate API Key');
                    if (!name) return;
                    
                    try {
                        const res = await fetch('/api/developer/keys', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({ name: name })
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.newlyCreatedKey = data.key;
                            this.showToast('API Key generated successfully');
                            await this.fetchDeveloperConsole();
                        } else {
                            this.showToast('Failed to generate key', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async revokeApiKey(id) {
                    if (!await this.askConfirm('Are you sure you want to revoke this API Key? Any programmatic integrations using it will immediately stop working.', 'Revoke API Key', true)) return;
                    try {
                        const res = await fetch(`/api/developer/keys/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('API Key revoked');
                            if (this.newlyCreatedKey && this.apiKeys.find(k => k.id === id)) {
                                this.newlyCreatedKey = '';
                            }
                            await this.fetchDeveloperConsole();
                        }
                    } catch(e) {}
                },
                
                openCreateWebhookModal() {
                    this.webhookForm = { url: '', events_str: '*' };
                    this.modals.createWebhook = true;
                    this.refreshIcons();
                },
                
                async submitCreateWebhook() {
                    if (!this.webhookForm.url) {
                        this.showToast('Destination URL is required', 'error');
                        return;
                    }
                    const events = this.webhookForm.events_str.split(',').map(e => e.trim()).filter(e => e.length > 0);
                    try {
                        const res = await fetch('/api/developer/webhooks', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({ url: this.webhookForm.url, events: events })
                        });
                        if (res.ok) {
                            this.modals.createWebhook = false;
                            this.showToast('Webhook endpoint configured');
                            await this.fetchDeveloperConsole();
                        } else {
                            const data = await res.json();
                            this.showToast(data.detail || 'Failed to create webhook', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async deleteWebhook(id) {
                    if (!await this.askConfirm('Are you sure you want to delete this webhook subscription?', 'Delete Webhook Subscription', true)) return;
                    try {
                        const res = await fetch(`/api/developer/webhooks/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Webhook subscription deleted');
                            await this.fetchDeveloperConsole();
                        }
                    } catch(e) {}
                },
                
                async triggerOidcLogin() {
                    try {
                        const res = await fetch('/api/auth/oidc/url');
                        const data = await res.json();
                        window.location.href = data.url;
                    } catch(e) {
                        this.showToast('Failed to start OIDC redirect', 'error');
                    }
                },
                
                handleLogout() {
                    localStorage.removeItem('polypress_token');
                    this.token = null;
                    this.authenticated = false;
                    this.user = {};
                    this.tenant = {};
                    this.loginForm = { email: '', password: '' };
                    this.showToast('Signed out successfully.');
                },
                
                async verifySession() {
                    try {
                        const res = await fetch('/api/auth/me', {
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
                        
                        if (!res.ok) throw new Error('Session expired');
                        
                        const data = await res.json();
                        this.user = data;
                        this.authenticated = true;
                        
                        // Handle pending approval block
                        if (this.user.role === 'pending') {
                            this.switchTab('pending_approval');
                            return;
                        }
                        
                        // Retrieve saved host admin mode preference (Super Admin only)
                        if (this.user.role === 'super_admin') {
                            const savedHostMode = localStorage.getItem('polypress_host_admin_mode');
                            this.hostAdminMode = savedHostMode !== 'false';
                        } else {
                            this.hostAdminMode = false;
                        }
                        
                        // Fetch accessible tenants (accessible to all logged-in users)
                        try {
                            const endpoint = (this.user && this.user.role === 'super_admin') ? '/api/tenants' : '/api/tenants/accessible';
                            const tenantsRes = await fetch(endpoint, { headers: { 'Authorization': `Bearer ${this.token}` } });
                            if (tenantsRes.ok) {
                                this.tenants = await tenantsRes.json();
                            }
                        } catch (e) {
                            console.error('Failed to fetch accessible tenants:', e);
                        }

                        if (this.user.role === 'super_admin') {
                            await this.fetchGlobalSettings();
                            await this.fetchUpdateStatus();
                            if (this.updateStatus && this.updateStatus.update_available) {
                                this.showToast('System Update Available! Go to Admin Panel to install.', 'info');
                            }
                        }
                        
                        // Load saved tenant context if not in host admin mode
                        if (!this.hostAdminMode) {
                            const savedTenant = localStorage.getItem('polypress_active_tenant');
                            if (savedTenant) {
                                const parsed = parseInt(savedTenant);
                                if (this.tenants.some(t => t.id === parsed)) {
                                    this.activeTenantId = parsed;
                                } else if (this.tenants.length > 0) {
                                    this.activeTenantId = this.tenants[0].id;
                                }
                            } else if (this.tenants.length > 0) {
                                this.activeTenantId = this.tenants[0].id;
                            }
                        }
                        
                        // Load context details
                        if (this.user.role === 'super_admin' && this.hostAdminMode) {
                            this.tenant = { name: 'PolyPress Console' };
                        } else {
                            await this.fetchTenant();
                        }
                        
                        await this.fetchCampaigns();
                        await this.fetchLists();
                        await this.loadDashboardMetrics();
                        
                        this.switchTab('dashboard');
                    } catch(e) {
                        this.handleLogout();
                    }
                },
                
                getAuthHeaders() {
                    const headers = {
                        'Authorization': `Bearer ${this.token}`,
                        'Content-Type': 'application/json'
                    };
                    if (this.user && (this.user.role !== 'super_admin' || !this.hostAdminMode) && this.activeTenantId) {
                        headers['X-PolyPress-Tenant-Id'] = String(this.activeTenantId);
                    }
                    return headers;
                },
                
                async toggleHostAdminMode() {
                    this.hostAdminMode = !this.hostAdminMode;
                    localStorage.setItem('polypress_host_admin_mode', this.hostAdminMode);
                    
                    // Reset selected context if switching back to host admin mode
                    if (this.hostAdminMode) {
                        this.activeTenantId = null;
                        this.tenant = { name: 'PolyPress Console' };
                        this.switchTab('dashboard');
                        this.fetchTenants();
                        this.fetchGlobalSettings();
                        await this.fetchCampaigns();
                        await this.fetchLists();
                        await this.loadDashboardMetrics();
                    } else {
                        // Switching to client workspace mode: select first tenant if any
                        if (this.tenants.length > 0 && !this.activeTenantId) {
                            this.activeTenantId = this.tenants[0].id;
                        }
                        await this.changeActiveTenantContext();
                    }
                    this.refreshIcons();
                },
                
                async changeActiveTenantContext() {
                    this.dnsTestResults = {
                        mx: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                        spf: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] }, spf_warning: '' },
                        dkim: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                        dmarc: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                        ptr: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } },
                        blacklist: { status: 'missing', sources: { local: [], cloudflare: [], google: [], quad9: [] } }
                    };
                    if (this.activeTenantId) {
                        localStorage.setItem('polypress_active_tenant', this.activeTenantId);
                    } else {
                        localStorage.removeItem('polypress_active_tenant');
                    }
                    
                    try {
                        if (this.user.role === 'super_admin' && this.hostAdminMode) {
                            this.tenant = { name: 'PolyPress Console' };
                        } else {
                            await this.fetchTenant();
                        }
                    } catch(e) {
                        this.tenant = { name: 'PolyPress Console' };
                    }
                    
                    // Clear list selections (Bug 8)
                    this.listSelected = null;
                    this.listSelectedName = '';
                    this.listSelectedFields = [];
                    this.subscribers = [];
                    this.subscribersCount = 0;
                    
                    // Re-load data in selected tenant context
                    await this.fetchCampaigns();
                    await this.fetchLists();
                    await this.loadDashboardMetrics();
                    
                    if (this.activeTab === 'reports') {
                        await this.fetchReportData();
                        await this.loadReportSettings();
                    } else {
                        this.switchTab('dashboard');
                    }
                    this.refreshIcons();
                },

                // User Management CRUD Actions
                async fetchUsers() {
                    try {
                        const res = await fetch('/api/admin/users', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.usersList = await res.json();
                        }
                        this.refreshIcons();
                    } catch(e) {
                        this.showToast('Failed to load user list', 'error');
                    }
                },
                
                openAddUserModal() {
                    const defaultTid = this.activeTenantId || this.user.tenant_id;
                    this.userForm = { 
                        id: null, 
                        email: '', 
                        name: '', 
                        password: '', 
                        role: 'tenant_user', 
                        tenant_id: defaultTid,
                        allowed_tenants: defaultTid ? [parseInt(defaultTid)] : [],
                        auth_type: 'local'
                    };
                    this.userModalOpen = true;
                    this.refreshIcons();
                },
                
                openEditUserModal(user) {
                    this.userForm = { 
                        id: user.id, 
                        email: user.email, 
                        name: user.name, 
                        password: '', 
                        role: user.role, 
                        tenant_id: user.tenant_id,
                        allowed_tenants: user.allowed_tenants || (user.tenant_id ? [user.tenant_id] : []),
                        auth_type: user.auth_type || 'local'
                    };
                    this.userModalOpen = true;
                    this.refreshIcons();
                },
                
                toggleUserFormTenant(id) {
                    if (!this.userForm.allowed_tenants) {
                        this.userForm.allowed_tenants = [];
                    }
                    const idx = this.userForm.allowed_tenants.indexOf(id);
                    if (idx > -1) {
                        this.userForm.allowed_tenants.splice(idx, 1);
                    } else {
                        this.userForm.allowed_tenants.push(id);
                    }
                    if (this.userForm.allowed_tenants.length > 0) {
                        this.userForm.tenant_id = this.userForm.allowed_tenants[0];
                    } else {
                        this.userForm.tenant_id = null;
                    }
                },
                
                async saveUser() {
                    if (!this.userForm.email || !this.userForm.name) {
                        this.showToast('Name and email are required', 'error');
                        return;
                    }
                    if (!this.userForm.id && this.userForm.auth_type === 'local' && !this.userForm.password) {
                        this.showToast('Password is required for new local credentials users', 'error');
                        return;
                    }
                    
                    try {
                        const isEdit = !!this.userForm.id;
                        const url = isEdit ? `/api/admin/users/${this.userForm.id}` : '/api/admin/users';
                        const method = isEdit ? 'PUT' : 'POST';
                        
                        const res = await fetch(url, {
                            method: method,
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.userForm)
                        });
                        
                        if (res.ok) {
                            this.showToast(isEdit ? 'User updated successfully' : 'User created successfully');
                            this.userModalOpen = false;
                            await this.fetchUsers();
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed to save user');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async updateUser(user) {
                    try {
                        const res = await fetch(`/api/admin/users/${user.id}`, {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(user)
                        });
                        if (res.ok) {
                            this.showToast('User updated');
                            await this.fetchUsers();
                        } else {
                            throw new Error('Failed to update user');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                        await this.fetchUsers();
                    }
                },
                
                async deleteUser(userId) {
                    if (!await this.askConfirm('Are you sure you want to delete this user?', 'Delete User Account', true)) return;
                    try {
                        const res = await fetch(`/api/admin/users/${userId}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('User deleted successfully');
                            await this.fetchUsers();
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed to delete user');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async resetUser2FA(user) {
                    if (!await this.askConfirm(`Are you sure you want to reset 2FA for ${user.name}? They will be able to log in without a 2FA prompt.`, 'Reset User 2FA', true)) return;
                    try {
                        const res = await fetch(`/api/admin/users/${user.id}`, {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({ reset_2fa: true })
                        });
                        if (res.ok) {
                            this.showToast('2FA has been disabled for this user');
                            await this.fetchUsers();
                        } else {
                            throw new Error('Failed to reset 2FA');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                // Profile Settings Actions
                openProfileModal() {
                    this.profileForm = { name: this.user.name, password: '' };
                    this.totpSetup.step = 1;
                    this.profileModalOpen = true;
                    this.refreshIcons();
                },
                
                async saveProfile() {
                    if (!this.profileForm.name) {
                        this.showToast('Name cannot be empty', 'error');
                        return;
                    }
                    try {
                        const payload = { name: this.profileForm.name };
                        if (this.profileForm.password) {
                            payload.password = this.profileForm.password;
                        }
                        
                        const res = await fetch(`/api/admin/users/${this.user.id}`, {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(payload)
                        });
                        
                        if (res.ok) {
                            this.showToast('Profile updated successfully');
                            this.user.name = this.profileForm.name;
                            this.profileModalOpen = false;
                        } else {
                            throw new Error('Failed to update profile');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async fetchTenant() {
                    try {
                        const res = await fetch('/api/tenants/my', { headers: this.getAuthHeaders() });
                        if (res.ok) this.tenant = await res.json();
                        
                        // Fetch server egress public IP asynchronously for overrides placeholder
                        const ipRes = await fetch('/api/tenants/my/detected-ip', { headers: this.getAuthHeaders() });
                        if (ipRes.ok) {
                            const data = await ipRes.json();
                            this.detectedPublicIp = data.public_ip;
                        }
                    } catch(e) {}
                },
                
                async fetchCampaigns() {
                    try {
                        const res = await fetch('/api/campaigns', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.campaigns = await res.json();
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },
                
                async fetchLists() {
                    try {
                        const res = await fetch('/api/lists', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.lists = await res.json();
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },
                
                async fetchTenants() {
                    try {
                        const endpoint = (this.user && this.user.role === 'super_admin') ? '/api/tenants' : '/api/tenants/accessible';
                        const res = await fetch(endpoint, { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.tenants = await res.json();
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },
                
                async fetchGlobalSettings() {
                    try {
                        const res = await fetch('/api/tenants/global-settings', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            const data = await res.json();
                            if (data) this.globalSettings = data;
                        }
                    } catch(e) {}
                },
                
                toggleOidcSetting() {
                    this.globalSettings.oidc_enabled = !this.globalSettings.oidc_enabled;
                    if (!this.globalSettings.oidc_enabled && !this.globalSettings.local_login_enabled) {
                        this.globalSettings.local_login_enabled = true;
                        this.showToast('At least one authentication method must be enabled. Local Auth remains on.', 'warning');
                    }
                },
                
                toggleLocalLoginSetting() {
                    this.globalSettings.local_login_enabled = !this.globalSettings.local_login_enabled;
                    if (!this.globalSettings.local_login_enabled && !this.globalSettings.oidc_enabled) {
                        this.globalSettings.oidc_enabled = true;
                        this.showToast('At least one authentication method must be enabled. OIDC Auth remains on.', 'warning');
                    }
                },

                async saveGlobalSettings() {
                    try {
                        const res = await fetch('/api/tenants/global-settings', {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.globalSettings)
                        });
                        if (res.ok) {
                            this.showToast('Global settings updated');
                            await this.fetchGlobalSettings();
                            await this.fetchUpdateStatus();
                        } else {
                            const err = await res.json();
                            let msg = 'Failed to save settings';
                            if (err.detail) {
                                if (typeof err.detail === 'string') {
                                    msg = err.detail;
                                } else if (Array.isArray(err.detail)) {
                                    msg = err.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ');
                                } else if (typeof err.detail === 'object') {
                                    msg = JSON.stringify(err.detail);
                                }
                            }
                            this.showToast(msg, 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async fetchBackups() {
                    if (this.user.role !== 'super_admin') return;
                    try {
                        const res = await fetch('/api/admin/backups', {
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.backups = await res.json();
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },

                async createBackup() {
                    try {
                        const res = await fetch('/api/admin/backups/create', {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.backups = data.backups;
                            this.showToast('Database snapshot generated successfully');
                            this.refreshIcons();
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed to create backup');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                async restoreBackup(filename) {
                    if (!await this.askConfirm('Are you absolutely sure you want to restore the system database from: ' + filename + '?\n\nWARNING: THIS WILL COMPLETELY OVERWRITE ALL DATA IN THE SYSTEM. This cannot be undone!', 'Restore Backup', true)) {
                        return;
                    }
                    try {
                        const res = await fetch('/api/admin/backups/restore-local?filename=' + encodeURIComponent(filename), {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('System backup restored successfully. Reloading...', 'success');
                            setTimeout(() => window.location.reload(), 1500);
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed to restore backup');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                async deleteBackup(filename) {
                    if (!await this.askConfirm('Are you sure you want to delete the backup snapshot ' + filename + '?', 'Delete Backup Snapshot', true)) {
                        return;
                    }
                    try {
                        const res = await fetch('/api/admin/backups/' + encodeURIComponent(filename), {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.backups = data.backups;
                            this.showToast('Backup snapshot deleted');
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },

                async uploadBackupRestoreFile(event) {
                    const file = event.target.files[0];
                    if (!file) return;
                    
                    if (!await this.askConfirm('Are you absolutely sure you want to upload and restore this backup ZIP archive?\n\nWARNING: THIS WILL COMPLETELY OVERWRITE ALL EXISTING DATA IN THE SYSTEM!', 'Upload & Restore Backup', true)) {
                        event.target.value = '';
                        return;
                    }
                    
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    try {
                        this.showToast('Uploading and restoring system snapshot...', 'info');
                        const res = await fetch('/api/admin/backups/restore', {
                            method: 'POST',
                            headers: {
                                'Authorization': this.getAuthHeaders()['Authorization']
                            },
                            body: formData
                        });
                        if (res.ok) {
                            this.showToast('System restore complete! Reloading workspace...', 'success');
                            setTimeout(() => window.location.reload(), 1500);
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Restore failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    } finally {
                        event.target.value = '';
                    }
                },
                
                async fetchUpdateStatus() {
                    if (this.user.role !== 'super_admin') return;
                    try {
                        const res = await fetch('/api/admin/update/status', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.updateStatus = await res.json();
                        }
                    } catch(e) {}
                },
                
                async checkUpdates() {
                    this.updateChecking = true;
                    try {
                        const res = await fetch('/api/admin/update/check', { method: 'POST', headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.updateStatus = await res.json();
                            this.showToast(this.updateStatus.update_available ? 'An update is available!' : 'Your system is up to date.');
                        }
                    } catch(e) {
                        this.showToast('Failed to check for updates', 'error');
                    } finally {
                        this.updateChecking = false;
                    }
                },
                
                async installUpdate() {
                    let warn = 'Are you sure you want to install this update?';
                    if (this.updateStatus.is_docker) {
                        warn += '\n\nℹ️ NOTE: Running in Docker. This update will apply a temporary hot-patch to the running container, which will revert if you pull a new image. The container will restart automatically.';
                    } else if (!this.updateStatus.is_systemd) {
                        warn += '\n\n⚠️ WARNING: PolyPress is not running under systemd. The server will shutdown to update, but will NOT restart automatically. You will need to start the process manually.';
                    } else {
                        warn += '\n\nThe server will restart automatically to apply updates.';
                    }
                    if (!await this.askConfirm(warn, 'Install Update', true)) return;
                    
                    this.updateInstalling = true;
                    try {
                        const res = await fetch('/api/admin/update/install', { method: 'POST', headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.showToast('Update started. Server is restarting...', 'success');
                            setTimeout(() => window.location.reload(), 6000);
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Install failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                        this.updateInstalling = false;
                    }
                },
                
                async forceBetaUpdate() {
                    let warn = 'Are you sure you want to force-pull the latest commit from the active branch?';
                    if (this.updateStatus.is_docker) {
                        warn += '\n\nℹ️ NOTE: Running in Docker. This will temporarily hot-patch the container with the latest commit from the active branch. Recreating the container will revert this change.';
                    } else if (!this.updateStatus.is_systemd) {
                        warn += '\n\n⚠️ WARNING: PolyPress is not running under systemd. The server will shutdown, but will NOT restart automatically.';
                    } else {
                        warn += '\n\nThe server will restart automatically.';
                    }
                    if (!await this.askConfirm(warn, 'Force Beta Update', true)) return;
                    
                    this.updateInstalling = true;
                    try {
                        const res = await fetch('/api/admin/update/force-beta', { method: 'POST', headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.showToast('Force pull initiated. Server is restarting...', 'success');
                            setTimeout(() => window.location.reload(), 6000);
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Force pull failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                        this.updateInstalling = false;
                    }
                },

                async submitSchemaBypass() {
                    if (!this.schemaBypassForm.email || !this.schemaBypassForm.password) {
                        this.showToast('Please fill out all fields', 'error');
                        return;
                    }
                    this.schemaBypassing = true;
                    try {
                        const res = await fetch('/api/admin/update/bypass-schema-check', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.schemaBypassForm)
                        });
                        if (res.ok) {
                            this.showToast('Bypass successful. Server is restarting...', 'success');
                            setTimeout(() => window.location.reload(), 5000);
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Authentication failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    } finally {
                        this.schemaBypassing = false;
                    }
                },
                
                generateBackupToken() {
                    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
                    let token = 'pp_backup_';
                    for (let i = 0; i < 32; i++) {
                        token += chars.charAt(Math.floor(Math.random() * chars.length));
                    }
                    this.globalSettings.backup_token = token;
                },
                
                async saveTenantSettings() {
                    try {
                        const res = await fetch('/api/tenants/my', {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.tenant)
                        });
                        if (res.ok) {
                            this.showToast('Settings saved successfully');
                            await this.fetchTenant();
                        } else {
                            throw new Error('Save error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async generateTenantDkimKeys() {
                    try {
                        const res = await fetch('/api/tenants/my/dkim', {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.tenant.dkim_public_key = data.dkim_public_key;
                            this.showToast('DKIM keys generated');
                        }
                    } catch(e) {}
                },
                
                switchTab(tab) {
                    if (tab !== 'editor') {
                        this.isEditingOptIn = false;
                        this.isEditingFooter = false;
                    }
                    if (tab !== 'reports') {
                        const canvas = document.getElementById('reportsChart');
                        if (canvas) {
                            const existingChart = Chart.getChart(canvas);
                            if (existingChart) {
                                try {
                                    existingChart.stop();
                                    existingChart.destroy();
                                } catch(e) {}
                            }
                        }
                        if (this.reportsChart) {
                            try {
                                this.reportsChart.stop();
                                this.reportsChart.destroy();
                            } catch(e) {}
                            this.reportsChart = null;
                        }
                        if (this.reportsChartTimeoutId) {
                            clearTimeout(this.reportsChartTimeoutId);
                            this.reportsChartTimeoutId = null;
                        }
                    }
                    
                    if (tab !== 'dashboard') {
                        const canvas = document.getElementById('subscriberChart');
                        if (canvas) {
                            const existingChart = Chart.getChart(canvas);
                            if (existingChart) {
                                try {
                                    existingChart.stop();
                                    existingChart.destroy();
                                } catch(e) {}
                            }
                        }
                        if (this.dashboardChart) {
                            try {
                                this.dashboardChart.stop();
                                this.dashboardChart.destroy();
                            } catch(e) {}
                            this.dashboardChart = null;
                        }
                        if (this.chartTimeoutId) {
                            clearTimeout(this.chartTimeoutId);
                            this.chartTimeoutId = null;
                        }
                    }
                    
                    this.activeTab = tab;
                    this.refreshIcons();
                    
                    if (tab === 'dashboard') {
                        this.loadDashboardMetrics();
                    } else if (tab === 'settings') {
                        this.fetchOutboxQueue();
                        this.fetchDeveloperConsole();
                        this.runDnsDiagnostics();
                    } else if (tab === 'admin') {
                        this.fetchTenants();
                        this.fetchGlobalSettings();
                        this.fetchSslStatus();
                        this.fetchBackups();
                        this.fetchUpdateStatus();
                    } else if (tab === 'users') {
                        this.fetchUsers();
                    } else if (tab === 'reports') {
                        this.fetchReportData();
                        this.loadReportSettings();
                    }
                },

                // Helper to format date in timezone
                formatReportDateTime(dateStr) {
                    if (!dateStr) return '';
                    const d = new Date(dateStr + (dateStr.endsWith('Z') ? '' : 'Z'));
                    const tz = this.reportsTimezone;
                    if (tz === 'local') {
                        return d.toLocaleString();
                    }
                    return d.toLocaleString('en-US', { timeZone: tz });
                },

                // Helper to pad metrics with zeros and convert UTC to timezone
                preparePaddedHistory(historyData, days, tz, endingDate = null) {
                    const resultPoints = [];
                    const referenceDate = endingDate ? new Date(endingDate) : new Date();
                    if (endingDate) {
                        referenceDate.setHours(23, 59, 59, 999);
                    }
                    
                    const firstRecordDate = historyData.length > 0 ? new Date(historyData[0].recorded_at + 'Z') : null;
                    
                    if (days === 1) {
                        // Hourly points for the last 24 hours
                        const hourlyPoints = [];
                        for (let i = 23; i >= 0; i--) {
                            const d = new Date(referenceDate.getTime() - i * 60 * 60 * 1000);
                            const label = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz === 'local' ? undefined : tz });
                            
                            const hourRecords = historyData.filter(r => {
                                const recDate = new Date(r.recorded_at + 'Z');
                                return Math.abs(recDate.getTime() - d.getTime()) <= 30 * 60 * 1000;
                            });
                            
                            hourlyPoints.push({
                                label: label,
                                records: hourRecords,
                                rawDate: d
                            });
                        }
                        
                        let lastSubs = 0;
                        let lastSent = null, lastOpens = null, lastClicks = null, lastBounces = null;
                        
                        for (let pt of hourlyPoints) {
                            const isBeforeFirstRecord = firstRecordDate && pt.rawDate < firstRecordDate;
                            
                            if (pt.records.length > 0) {
                                pt.records.sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at));
                                const latest = pt.records[pt.records.length - 1];
                                
                                if (lastSent === null) {
                                    lastSubs = latest.subscriber_count;
                                    lastSent = latest.emails_sent;
                                    lastOpens = latest.email_opens;
                                    lastClicks = latest.link_clicks;
                                    lastBounces = latest.bounces;
                                }
                                
                                const sentDiff = Math.max(0, latest.emails_sent - lastSent);
                                const opensDiff = Math.max(0, latest.email_opens - lastOpens);
                                const clicksDiff = Math.max(0, latest.link_clicks - lastClicks);
                                const bouncesDiff = Math.max(0, latest.bounces - lastBounces);
                                
                                resultPoints.push({
                                    date: pt.label,
                                    subscriber_count: latest.subscriber_count,
                                    emails_sent: sentDiff,
                                    email_opens: opensDiff,
                                    link_clicks: clicksDiff,
                                    bounces: bouncesDiff,
                                    recorded_at: latest.recorded_at
                                });
                                
                                lastSubs = latest.subscriber_count;
                                lastSent = latest.emails_sent;
                                lastOpens = latest.email_opens;
                                lastClicks = latest.link_clicks;
                                lastBounces = latest.bounces;
                            } else {
                                if (isBeforeFirstRecord) {
                                    resultPoints.push({
                                        date: pt.label,
                                        subscriber_count: 0,
                                        emails_sent: 0,
                                        email_opens: 0,
                                        link_clicks: 0,
                                        bounces: 0,
                                        recorded_at: pt.rawDate.toISOString()
                                    });
                                } else {
                                    resultPoints.push({
                                        date: pt.label,
                                        subscriber_count: lastSubs,
                                        emails_sent: 0,
                                        email_opens: 0,
                                        link_clicks: 0,
                                        bounces: 0,
                                        recorded_at: pt.rawDate.toISOString()
                                    });
                                }
                            }
                        }
                    } else {
                        // Daily points for X days
                        const dailyPoints = [];
                        for (let i = days - 1; i >= 0; i--) {
                            const d = new Date(referenceDate.getTime() - i * 24 * 60 * 60 * 1000);
                            const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: tz === 'local' ? undefined : tz });
                            
                            const dayRecords = historyData.filter(r => {
                                const recDate = new Date(r.recorded_at + 'Z');
                                const recLabel = recDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: tz === 'local' ? undefined : tz });
                                return recLabel === label;
                            });
                            
                            dailyPoints.push({
                                label: label,
                                records: dayRecords,
                                rawDate: d
                            });
                        }
                        
                        let lastSubs = 0;
                        let lastSent = null, lastOpens = null, lastClicks = null, lastBounces = null;
                        
                        for (let pt of dailyPoints) {
                            const isBeforeFirstRecord = firstRecordDate && pt.rawDate < firstRecordDate;
                            
                            if (pt.records.length > 0) {
                                pt.records.sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at));
                                const latest = pt.records[pt.records.length - 1];
                                
                                if (lastSent === null) {
                                    lastSubs = latest.subscriber_count;
                                    lastSent = latest.emails_sent;
                                    lastOpens = latest.email_opens;
                                    lastClicks = latest.link_clicks;
                                    lastBounces = latest.bounces;
                                }
                                
                                const sentDiff = Math.max(0, latest.emails_sent - lastSent);
                                const opensDiff = Math.max(0, latest.email_opens - lastOpens);
                                const clicksDiff = Math.max(0, latest.link_clicks - lastClicks);
                                const bouncesDiff = Math.max(0, latest.bounces - lastBounces);
                                
                                resultPoints.push({
                                    date: pt.label,
                                    subscriber_count: latest.subscriber_count,
                                    emails_sent: sentDiff,
                                    email_opens: opensDiff,
                                    link_clicks: clicksDiff,
                                    bounces: bouncesDiff,
                                    recorded_at: latest.recorded_at
                                });
                                
                                lastSubs = latest.subscriber_count;
                                lastSent = latest.emails_sent;
                                lastOpens = latest.email_opens;
                                lastClicks = latest.link_clicks;
                                lastBounces = latest.bounces;
                            } else {
                                if (isBeforeFirstRecord) {
                                    resultPoints.push({
                                        date: pt.label,
                                        subscriber_count: 0,
                                        emails_sent: 0,
                                        email_opens: 0,
                                        link_clicks: 0,
                                        bounces: 0,
                                        recorded_at: pt.rawDate.toISOString()
                                    });
                                } else {
                                    resultPoints.push({
                                        date: pt.label,
                                        subscriber_count: lastSubs,
                                        emails_sent: 0,
                                        email_opens: 0,
                                        link_clicks: 0,
                                        bounces: 0,
                                        recorded_at: pt.rawDate.toISOString()
                                    });
                                }
                            }
                        }
                    }
                    if (historyData.length > 0) {
                        let firstActiveIdx = -1;
                        let lastActiveIdx = -1;
                        
                        const activeLabels = new Set(historyData.map(r => {
                            const recDate = new Date(r.recorded_at + 'Z');
                            if (days === 1) {
                                return recDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz === 'local' ? undefined : tz });
                            } else {
                                return recDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: tz === 'local' ? undefined : tz });
                            }
                        }));
                        
                        for (let i = 0; i < resultPoints.length; i++) {
                            if (activeLabels.has(resultPoints[i].date)) {
                                if (firstActiveIdx === -1) {
                                    firstActiveIdx = i;
                                }
                                lastActiveIdx = i;
                            }
                        }
                        
                        if (firstActiveIdx !== -1 && lastActiveIdx !== -1) {
                            return resultPoints.slice(firstActiveIdx, lastActiveIdx + 1);
                        }
                    }
                    return resultPoints;
                },

                // Dashboard Metrics calculator
                async loadDashboardMetrics() {
                    this.loadingDashboardStats = true;
                    try {
                        // Summarize current totals
                        this.stats.totalSubscribers = 0;
                        let sumSubs = 0;
                        for (let l of this.lists) {
                            try {
                                const res = await fetch(`/api/lists/${l.id}/subscribers?limit=1&status=active`, { headers: this.getAuthHeaders() });
                                const data = await res.json();
                                sumSubs += data.total;
                            } catch(e) {}
                        }
                        this.stats.totalSubscribers = sumSubs;
                        
                        // Fetch history data for current period (X days) and previous period (2X days)
                        let historyData = [];
                        try {
                            const daysToFetch = this.dashboardPeriod * 2;
                            const startDateStr = new Date(Date.now() - (daysToFetch * 24 * 60 * 60 * 1000)).toISOString().split('T')[0];
                            const res = await fetch(`/api/reports/history?start_date=${startDateStr}`, { headers: this.getAuthHeaders() });
                            if (res.ok) {
                                historyData = await res.json();
                            }
                        } catch(e) {}
                        
                        const now = new Date();
                        const periodMs = this.dashboardPeriod * 24 * 60 * 60 * 1000;
                        const currentStart = new Date(now.getTime() - periodMs);
                        const prevStart = new Date(now.getTime() - 2 * periodMs);
                        
                        // 1. Total Subscribers (current vs previous final)
                        const currentPeriodRecs = historyData.filter(r => new Date(r.recorded_at + 'Z') >= currentStart);
                        const prevPeriodRecs = historyData.filter(r => new Date(r.recorded_at + 'Z') >= prevStart && new Date(r.recorded_at + 'Z') < currentStart);
                        
                        let currentSubs = this.stats.totalSubscribers;
                        let prevSubs = 0;
                        
                        const olderRecs = historyData.filter(r => new Date(r.recorded_at + 'Z') < currentStart);
                        if (olderRecs.length > 0) {
                            olderRecs.sort((a, b) => new Date(a.recorded_at + 'Z') - new Date(b.recorded_at + 'Z'));
                            prevSubs = olderRecs[olderRecs.length - 1].subscriber_count;
                        } else {
                            prevSubs = 0;
                        }
                        this.trends.subscribers.diff = currentSubs - prevSubs;
                        
                        // 2. Campaigns Sent in current vs previous
                        const currentCampaigns = this.campaigns.filter(c => (c.status === 'sent' || c.status === 'sending') && new Date(c.created_at) >= currentStart);
                        const prevCampaigns = this.campaigns.filter(c => (c.status === 'sent' || c.status === 'sending') && new Date(c.created_at) >= prevStart && new Date(c.created_at) < currentStart);
                        
                        this.trends.campaigns.diff = currentCampaigns.length - prevCampaigns.length;
                        this.stats.campaignsSent = currentCampaigns.length;
                        
                        // 3. Open Rate and Bounce Rate averages for current period
                        let currentSent = currentCampaigns.reduce((sum, c) => sum + (c.sent_count || 0), 0);
                        let currentOpens = currentCampaigns.reduce((sum, c) => sum + (c.open_count || 0), 0);
                        let currentBounces = currentCampaigns.reduce((sum, c) => sum + (c.bounce_count || 0), 0);
                        
                        this.stats.avgOpenRate = currentSent > 0 ? Math.round((currentOpens / currentSent) * 100) : 0;
                        this.stats.avgBounceRate = currentSent > 0 ? Math.round((currentBounces / currentSent) * 100) : 0;
                        
                        // Previous period open/bounce averages
                        let prevSent = prevCampaigns.reduce((sum, c) => sum + (c.sent_count || 0), 0);
                        let prevOpens = prevCampaigns.reduce((sum, c) => sum + (c.open_count || 0), 0);
                        let prevBounces = prevCampaigns.reduce((sum, c) => sum + (c.bounce_count || 0), 0);
                        
                        let prevOpenRate = prevSent > 0 ? Math.round((prevOpens / prevSent) * 100) : 0;
                        let prevBounceRate = prevSent > 0 ? Math.round((prevBounces / prevSent) * 100) : 0;
                        
                        this.trends.openRate.diff = this.stats.avgOpenRate - prevOpenRate;
                        this.trends.bounceRate.diff = this.stats.avgBounceRate - prevBounceRate;
                        
                        // Generate padded history for chart rendering
                        const chartPoints = this.preparePaddedHistory(currentPeriodRecs, this.dashboardPeriod, this.reportsTimezone);
                        this.renderMetricsChart(chartPoints);
                    } finally {
                        this.loadingDashboardStats = false;
                    }
                },
                
                renderMetricsChart(chartPoints) {
                    if (this.chartTimeoutId) {
                        clearTimeout(this.chartTimeoutId);
                        this.chartTimeoutId = null;
                    }
                    if (this.dashboardChart) {
                        try {
                            this.dashboardChart.stop();
                            this.dashboardChart.destroy();
                        } catch(e) {}
                        this.dashboardChart = null;
                    }
                    this.chartTimeoutId = setTimeout(() => {
                        this.chartTimeoutId = null;
                        if (this.activeTab !== 'dashboard') return;
                        const ctx = document.getElementById('dashboardChart');
                        if (!ctx) return;
                        
                        const labels = chartPoints.map(p => p.date);
                        const opensData = chartPoints.map(p => p.email_opens);
                        const clicksData = chartPoints.map(p => p.link_clicks);
                        
                        try {
                            this.dashboardChart = new Chart(ctx, {
                                type: 'line',
                                data: {
                                    labels: labels.length ? labels : ['No Data'],
                                    datasets: [
                                        {
                                            label: 'Email Opens',
                                            data: opensData.length ? opensData : [0],
                                            borderColor: '#10b981',
                                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                                            tension: 0.3,
                                            fill: true
                                        },
                                        {
                                            label: 'Link Clicks',
                                            data: clicksData.length ? clicksData : [0],
                                            borderColor: '#6366f1',
                                            backgroundColor: 'rgba(99, 102, 241, 0.1)',
                                            tension: 0.3,
                                            fill: true
                                        }
                                    ]
                                },
                                options: {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    animation: {
                                        duration: 1000,
                                        easing: 'easeOutQuart',
                                        delay: (context) => {
                                            if (context.type === 'data' && context.mode === 'default') {
                                                return context.dataIndex * 17;
                                            }
                                            return 0;
                                        }
                                    },
                                    plugins: {
                                        legend: {
                                            labels: { color: '#94a3b8' }
                                        }
                                    },
                                    scales: {
                                        y: {
                                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                                            ticks: { color: '#94a3b8' }
                                        },
                                        x: {
                                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                                            ticks: { color: '#94a3b8' }
                                        }
                                    }
                                }
                            });
                        } catch(e) {
                            console.error('Failed to create dashboard chart:', e);
                        }
                    }, 50);
                },
                
                // Create Campaign Actions
                openCreateCampaignModal() {
                    this.campaignForm = { name: '', subject: '', list_id: '', list_ids: [] };
                    this.modals.createCampaign = true;
                    this.refreshIcons();
                },
                
                openEditCampaignModal(campaign) {
                    this.campaignForm = {
                        id: campaign.id,
                        name: campaign.name,
                        subject: campaign.subject,
                        list_id: campaign.list_id,
                        list_ids: campaign.list_ids ? [...campaign.list_ids] : (campaign.list_id ? [campaign.list_id] : [])
                    };
                    this.modals.createCampaign = true;
                    this.refreshIcons();
                },
                
                toggleCampaignFormList(id) {
                    if (!this.campaignForm.list_ids) {
                        this.campaignForm.list_ids = [];
                    }
                    const idx = this.campaignForm.list_ids.indexOf(id);
                    if (idx > -1) {
                        this.campaignForm.list_ids.splice(idx, 1);
                    } else {
                        this.campaignForm.list_ids.push(id);
                    }
                    if (this.campaignForm.list_ids.length > 0) {
                        this.campaignForm.list_id = this.campaignForm.list_ids[0];
                    } else {
                        this.campaignForm.list_id = '';
                    }
                },
                
                async submitCreateCampaign() {
                    try {
                        const isEdit = !!this.campaignForm.id;
                        const url = isEdit ? `/api/campaigns/${this.campaignForm.id}` : '/api/campaigns';
                        const method = isEdit ? 'PUT' : 'POST';
                        
                        const res = await fetch(url, {
                            method: method,
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.campaignForm)
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.modals.createCampaign = false;
                            await this.fetchCampaigns();
                            if (!isEdit) {
                                this.startVisualEditor(data);
                            } else {
                                this.showToast('Campaign settings updated successfully!');
                            }
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || `Failed to ${isEdit ? 'update' : 'create'} campaign`);
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async duplicateCampaign(id) {
                    try {
                        const res = await fetch(`/api/campaigns/${id}/duplicate`, {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Campaign duplicated successfully');
                            await this.fetchCampaigns();
                        }
                    } catch(e) {}
                },
                
                async deleteCampaign(id) {
                    if (!await this.askConfirm('Are you sure you want to delete this campaign permanently?', 'Delete Campaign', true)) return;
                    try {
                        const res = await fetch(`/api/campaigns/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Campaign deleted');
                            await this.fetchCampaigns();
                        }
                    } catch(e) {}
                },

                // List management
                openCreateListModal() {
                    this.listForm = { name: '', description: '' };
                    this.modals.createList = true;
                    this.refreshIcons();
                },
                
                async submitCreateList() {
                    try {
                        const res = await fetch('/api/lists', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.listForm)
                        });
                        if (res.ok) {
                            this.modals.createList = false;
                            this.showToast('Subscriber list created');
                            await this.fetchLists();
                        }
                    } catch(e) {}
                },
                
                async deleteList(id) {
                    if (!await this.askConfirm('Delete this subscriber list and all containing contacts permanently?', 'Delete Subscriber List', true)) return;
                    try {
                        const res = await fetch(`/api/lists/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Subscriber list deleted');
                            await this.fetchLists();
                            this.listSelected = null;
                        }
                    } catch(e) {}
                },

                // Schema control
                openEditListFieldsModal(list) {
                    this.fieldsListTarget = JSON.parse(JSON.stringify(list)); // deep clone
                    if (!this.fieldsListTarget.form_settings) {
                        this.fieldsListTarget.form_settings = { name_required: false };
                    }
                    this.newField = { label: '', key: '', required: false };
                    this.modals.editFields = true;
                    this.refreshIcons();
                },
                
                addCustomFieldToListSchema() {
                    const label = this.newField.label.trim();
                    const key = this.newField.key.trim().toLowerCase().replace(/[^a-z0-9_]/g, '');
                    if (!label || !key) return;
                    
                    if (!this.fieldsListTarget.custom_fields) {
                        this.fieldsListTarget.custom_fields = [];
                    }
                    
                    // Verify uniqueness
                    if (this.fieldsListTarget.custom_fields.find(f => f.key === key)) {
                        this.showToast('Key already exists', 'error');
                        return;
                    }
                    
                    this.fieldsListTarget.custom_fields.push({ key, label, type: 'text', required: !!this.newField.required });
                    this.newField = { label: '', key: '', required: false };
                    this.refreshIcons();
                },
                
                async saveCustomFieldsSchema() {
                    try {
                        const res = await fetch(`/api/lists/${this.fieldsListTarget.id}`, {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                name: this.fieldsListTarget.name,
                                description: this.fieldsListTarget.description,
                                custom_fields: this.fieldsListTarget.custom_fields,
                                form_settings: this.fieldsListTarget.form_settings
                            })
                        });
                        if (res.ok) {
                            this.showToast('Schema saved successfully');
                            this.modals.editFields = false;
                            await this.fetchLists();
                            if (this.listSelected && this.listSelected.id === this.fieldsListTarget.id) {
                                // refresh open browser
                                const updatedList = this.lists.find(l => l.id === this.listSelected.id);
                                this.browseListSubscribers(updatedList);
                            }
                        }
                    } catch(e) {}
                },

                // Contacts browser
                browseListSubscribers(list) {
                    this.listSelected = list.id;
                    this.listSelectedName = list.name;
                    this.listSelectedFields = list.custom_fields || [];
                    this.subscribersPage = 1;
                    this.subscribersSearch = '';
                    this.subscribersFilterStatus = '';
                    this.subscribersFilterEngagement = '';
                    this.subscribersFilterTag = '';
                    this.fetchSubscribers();
                },
                
                async fetchSubscribers() {
                    if (this.listSelected === null) return;
                    try {
                        let url = `/api/lists/${this.listSelected}/subscribers?page=${this.subscribersPage}&search=${encodeURIComponent(this.subscribersSearch)}`;
                        if (this.subscribersFilterStatus) url += `&status=${this.subscribersFilterStatus}`;
                        if (this.subscribersFilterEngagement) url += `&engagement=${this.subscribersFilterEngagement}`;
                        if (this.subscribersFilterTag) url += `&tag=${encodeURIComponent(this.subscribersFilterTag)}`;
                        
                        const res = await fetch(url, {
                            headers: this.getAuthHeaders()
                        });
                        const data = await res.json();
                        this.subscribers = data.subscribers;
                        this.subscribersCount = data.total;
                        this.refreshIcons();
                    } catch(e) {}
                },
                
                openAddSubscriberModal() {
                    this.subscriberForm = { id: null, email: '', name: '', status: 'active', tags: '', custom_data: {} };
                    for (let f of this.listSelectedFields) {
                        this.subscriberForm.custom_data[f.key] = '';
                    }
                    this.modals.addSubscriber = true;
                    this.refreshIcons();
                },
                
                openEditSubscriberModal(s) {
                    this.subscriberForm = {
                        id: s.id,
                        email: s.email,
                        name: s.name,
                        status: s.status || 'active',
                        tags: s.tags ? s.tags.join(', ') : '',
                        custom_data: { ...s.custom_data }
                    };
                    for (let f of this.listSelectedFields) {
                        if (this.subscriberForm.custom_data[f.key] === undefined) {
                            this.subscriberForm.custom_data[f.key] = '';
                        }
                    }
                    this.modals.addSubscriber = true;
                    this.refreshIcons();
                },
                
                async submitAddSubscriber() {
                    try {
                        const tagsList = this.subscriberForm.tags ? this.subscriberForm.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
                        const payload = {
                            email: this.subscriberForm.email,
                            name: this.subscriberForm.name,
                            status: this.subscriberForm.status,
                            tags: tagsList,
                            custom_data: this.subscriberForm.custom_data
                        };
                        const url = this.subscriberForm.id ? `/api/lists/${this.listSelected}/subscribers` : `/api/lists/${this.listSelected}/subscribers`;
                        const res = await fetch(url, {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(payload)
                        });
                        if (res.ok) {
                            this.modals.addSubscriber = false;
                            this.showToast(this.subscriberForm.id ? 'Contact updated' : 'Contact added');
                            await this.fetchSubscribers();
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async deleteSubscriber(subId) {
                    if (!await this.askConfirm('Remove this subscriber from the list?', 'Remove Contact', true)) return;
                    try {
                        const res = await fetch(`/api/lists/${this.listSelected}/subscribers/${subId}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Contact removed');
                            await this.fetchSubscribers();
                        }
                    } catch(e) {}
                },

                // Embed codes
                openEmbedCodeModal(list) {
                    this.fieldsListTarget = list;
                    this.embedCodeTag = 'Website Embed';
                    this.embedCodeTheme = 'dark';
                    this.updateEmbedCodeString();
                    this.modals.embedCode = true;
                    this.refreshIcons();
                },
                
                updateEmbedCodeString() {
                    const host = window.location.origin;
                    this.embedIframeSrc = `${host}/api/embed/subscribe/${this.fieldsListTarget.id}?tag=${encodeURIComponent(this.embedCodeTag)}&theme=${this.embedCodeTheme}`;
                    const bg = this.embedCodeTheme === 'light' ? '#f8fafc' : '#0f172a';
                    const border = this.embedCodeTheme === 'light' ? '1px solid #e2e8f0' : '1px solid rgba(255,255,255,0.08)';
                    this.embedCodeString = `<iframe src="${this.embedIframeSrc}" width="100%" height="450" style="border:${border}; border-radius:12px; background:${bg};" title="Newsletter Signup"></iframe>`;
                },

                // CSV Database Importer
                openCsvImportModal(list) {
                    this.csvListTarget = list;
                    this.csvFile = null;
                    this.csvHeaders = [];
                    this.csvMapping = { email: '', name: '', custom_fields: {} };
                    this.csvImportStep = 1;
                    this.modals.csvImport = true;
                    this.refreshIcons();
                },
                
                async handleCsvFileSelected(e) {
                    const file = e.target.files[0];
                    if (!file) return;
                    
                    this.csvFile = file;
                    
                    // Parse headers
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    try {
                        const res = await fetch(`/api/lists/${this.csvListTarget.id}/parse-headers`, {
                            method: 'POST',
                            headers: { 'Authorization': `Bearer ${this.token}` },
                            body: formData
                        });
                        
                        if (!res.ok) {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed parsing headers');
                        }
                        
                        const data = await res.json();
                        this.csvHeaders = data.headers;
                        
                        // Prefill matches if names align
                        this.csvHeaders.forEach(h => {
                            const lower = h.toLowerCase();
                            if (lower === 'email' || lower === 'email address' || lower === 'email_address') {
                                this.csvMapping.email = h;
                            }
                            if (lower === 'name' || lower === 'fullname' || lower === 'full name' || lower === 'contact name') {
                                this.csvMapping.name = h;
                            }
                            
                            // custom attributes
                            if (this.csvListTarget.custom_fields) {
                                this.csvListTarget.custom_fields.forEach(f => {
                                    if (lower === f.key.toLowerCase() || lower === f.label.toLowerCase()) {
                                        this.csvMapping.custom_fields[f.key] = h;
                                    }
                                });
                            }
                        });
                        
                        this.csvImportStep = 2;
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async submitCsvImport() {
                    if (!this.csvMapping.email) {
                        this.showToast('Please select the email column mapping', 'error');
                        return;
                    }
                    
                    this.csvImportStep = 3;
                    
                    const formData = new FormData();
                    formData.append('file', this.csvFile);
                    formData.append('mapping', JSON.stringify(this.csvMapping));
                    
                    try {
                        const res = await fetch(`/api/lists/${this.csvListTarget.id}/import`, {
                            method: 'POST',
                            headers: { 'Authorization': `Bearer ${this.token}` },
                            body: formData
                        });
                        
                        if (!res.ok) throw new Error('Import execution failed');
                        
                        const data = await res.json();
                        this.showToast(`Import finished! Added/updated: ${data.imported}. Skipped: ${data.skipped}`);
                        this.modals.csvImport = false;
                        await this.fetchLists();
                        if (this.listSelected === this.csvListTarget.id) {
                            await this.fetchSubscribers();
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                        this.csvImportStep = 2;
                    }
                },

                startVisualEditor(campaign) {
                    this.editingCampaign = campaign;
                    if (!this.editingCampaign.target_rules) {
                        this.editingCampaign.target_rules = { tag: '', engagement: [], signup_after: '', signup_before: '' };
                    } else {
                        if (typeof this.editingCampaign.target_rules.engagement === 'string') {
                            const prev = this.editingCampaign.target_rules.engagement;
                            this.editingCampaign.target_rules.engagement = prev ? [parseInt(prev)] : [];
                        } else if (!this.editingCampaign.target_rules.engagement) {
                            this.editingCampaign.target_rules.engagement = [];
                        }
                    }
                    if (!this.editingCampaign.list_ids) {
                        this.editingCampaign.list_ids = this.editingCampaign.list_id ? [this.editingCampaign.list_id] : [];
                    }
                    this.targetingCollapsed = true;
                    this.selectedBlockIndex = null;
                    this.editorBlocks = campaign.body_blocks || [];
                    this.switchTab('editor');
                },
                
                toggleEditingCampaignList(id) {
                    if (!this.editingCampaign.list_ids) {
                        this.editingCampaign.list_ids = [];
                    }
                    const idx = this.editingCampaign.list_ids.indexOf(id);
                    if (idx > -1) {
                        this.editingCampaign.list_ids.splice(idx, 1);
                    } else {
                        this.editingCampaign.list_ids.push(id);
                    }
                    if (this.editingCampaign.list_ids.length > 0) {
                        this.editingCampaign.list_id = this.editingCampaign.list_ids[0];
                    } else {
                        this.editingCampaign.list_id = '';
                    }
                },
                
                toggleTargetingRulesCollapse() {
                    this.targetingCollapsed = !this.targetingCollapsed;
                    this.refreshIcons();
                },
                
                getActiveListFields() {
                    const l = this.lists.find(x => x.id === this.editingCampaign.list_id);
                    return l ? (l.custom_fields || []) : [];
                },
                
                addEditorBlock(type) {
                    let block = { type };
                    if (type === 'heading') {
                        block = { type, text: 'Heading Text', align: 'center', color: '#1e293b', size: '28px', padding: '12px 0px' };
                    } else if (type === 'paragraph') {
                        block = { type, text: 'Write your content body here. Double curly tags like {{name}} will auto-inject values.', align: 'left', color: '#334155', size: '16px', padding: '10px 0px' };
                    } else if (type === 'button') {
                        block = { type, text: 'Click Link', url: 'https://example.com', align: 'center', bg_color: '#6366f1', text_color: '#ffffff', padding: '12px 24px', border_radius: '6px' };
                    } else if (type === 'image') {
                        block = { type, url: 'https://picsum.photos/600/300', alt: 'Marketing Banner', border_radius: '0px' };
                    } else if (type === 'divider') {
                        block = { type, color: '#e2e8f0', height: '2px', padding: '20px 0px' };
                    } else if (type === 'spacer') {
                        block = { type, height: '25px' };
                    } else if (type === 'columns') {
                        block = { 
                            type, 
                            layout: '50-50', 
                            gap: '20px',
                            left: { type: 'paragraph', text: 'Left Content', align: 'left', color: '#334155', size: '15px' },
                            right: { type: 'paragraph', text: 'Right Content', align: 'left', color: '#334155', size: '15px' }
                        };
                    }
                    
                    this.editorBlocks.push(block);
                    this.selectedBlockIndex = this.editorBlocks.length - 1;
                    this.reRenderCanvas();
                },
                
                moveBlock(from, to) {
                    if (from === null || to === null || from === to) return;
                    const block = this.editorBlocks.splice(from, 1)[0];
                    this.editorBlocks.splice(to, 0, block);
                    this.selectedBlockIndex = to;
                    this.reRenderCanvas();
                    this.reRenderCanvas();
                },
                
                moveBlockUp(idx) {
                    if (idx === 0) return;
                    const temp = this.editorBlocks[idx];
                    this.editorBlocks[idx] = this.editorBlocks[idx - 1];
                    this.editorBlocks[idx - 1] = temp;
                    this.selectedBlockIndex = idx - 1;
                    this.reRenderCanvas();
                },
                
                moveBlockDown(idx) {
                    if (idx === this.editorBlocks.length - 1) return;
                    const temp = this.editorBlocks[idx];
                    this.editorBlocks[idx] = this.editorBlocks[idx + 1];
                    this.editorBlocks[idx + 1] = temp;
                    this.selectedBlockIndex = idx + 1;
                    this.reRenderCanvas();
                },
                
                deleteBlock(idx) {
                    this.editorBlocks.splice(idx, 1);
                    this.selectedBlockIndex = null;
                    this.reRenderCanvas();
                },
                
                reRenderCanvas() {
                    // Forces Alpine to refresh layouts
                    this.editorBlocks = [...this.editorBlocks];
                    this.refreshIcons();
                },
                
                async saveCampaignDraft() {
                    const html = compileBlocksToHtml(this.editorBlocks, this.tenant.email_footer_html);
                    try {
                        const res = await fetch(`/api/campaigns/${this.editingCampaign.id}`, {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                name: this.editingCampaign.name,
                                subject: this.editingCampaign.subject,
                                body_blocks: this.editorBlocks,
                                body_html: html,
                                target_rules: this.editingCampaign.target_rules,
                                list_ids: this.editingCampaign.list_ids
                            })
                        });
                        if (res.ok) {
                            this.showToast('Campaign draft saved successfully');
                            await this.fetchCampaigns();
                        }
                    } catch(e) {}
                },
                
                openLaunchModal() {
                    this.modals.confirmLaunch = true;
                    this.refreshIcons();
                },
                
                async submitLaunchCampaign() {
                    this.modals.confirmLaunch = false;
                    const html = compileBlocksToHtml(this.editorBlocks, this.tenant.email_footer_html);
                    try {
                          await fetch(`/api/campaigns/${this.editingCampaign.id}`, {
                              method: 'PUT',
                              headers: this.getAuthHeaders(),
                              body: JSON.stringify({
                                  name: this.editingCampaign.name,
                                  subject: this.editingCampaign.subject,
                                  preheader: this.editingCampaign.preheader,
                                  body_blocks: this.editorBlocks,
                                  body_html: html,
                                  target_rules: this.editingCampaign.target_rules,
                                  list_ids: this.editingCampaign.list_ids
                              })
                          });
                          
                          const launchPayload = {};
                          if (this.launchScheduling.enabled && this.launchScheduling.date) {
                              launchPayload.scheduled_send_at = this.launchScheduling.date;
                              launchPayload.timezone = this.launchScheduling.timezone;
                          }
                          
                          const res = await fetch(`/api/campaigns/${this.editingCampaign.id}/launch`, {
                              method: 'POST',
                              headers: {
                                  ...this.getAuthHeaders(),
                                  'Content-Type': 'application/json'
                              },
                              body: JSON.stringify(launchPayload)
                          });
                          
                          if (res.ok) {
                              this.showToast('Broadcast queue initiated!');
                              await this.fetchCampaigns();
                              this.switchTab('campaigns');
                          } else {
                              const err = await res.json();
                              throw new Error(err.detail || 'Failed');
                          }
                      } catch(e) {
                          this.showToast(e.message, 'error');
                      }
                },

                async pauseCampaign(id) {
                    try {
                        const res = await fetch(`/api/campaigns/${id}/pause`, {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Campaign sending paused');
                            await this.fetchCampaigns();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to pause campaign', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async resumeCampaign(id) {
                    try {
                        const res = await fetch(`/api/campaigns/${id}/resume`, {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Campaign sending resumed');
                            await this.fetchCampaigns();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to resume campaign', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                async cancelCampaign(id) {
                    if (!await this.askConfirm('Are you sure you want to cancel sending this campaign? This will delete all unsent messages in the queue.', 'Cancel Broadcast', true)) return;
                    try {
                        const res = await fetch(`/api/campaigns/${id}/cancel`, {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Campaign broadcast cancelled');
                            await this.fetchCampaigns();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to cancel campaign', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                // Stats logs
                async openStatsModal(campaignId) {
                    this.showClickMapVisualizer = false;
                    this.clickMapHtml = '';
                    this.clickMapStats = [];
                    try {
                        const res = await fetch(`/api/campaigns/${campaignId}/stats`, { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.campaignStats = await res.json();
                            this.campaignStats.id = campaignId;
                            this.modals.stats = true;
                            this.refreshIcons();
                        }
                    } catch(e) {}
                },
                
                async loadClickMapOverlay() {
                    const campaignId = this.campaignStats.id;
                    if (!campaignId) return;
                    try {
                        const res = await fetch(`/api/campaigns/${campaignId}/click-map`, { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            const data = await res.json();
                            this.clickMapHtml = data.body_html;
                            this.clickMapStats = data.click_map;
                            
                            setTimeout(() => {
                                const iframe = document.getElementById('clickMapIframe');
                                if (!iframe) return;
                                
                                iframe.srcdoc = this.clickMapHtml || '<p style="color:#000; padding:20px;">No HTML template available.</p>';
                                iframe.onload = () => {
                                    const doc = iframe.contentDocument || iframe.contentWindow.document;
                                    if (!doc) return;
                                    
                                    const style = doc.createElement('style');
                                    style.textContent = `
                                        .click-overlay-bubble {
                                            position: absolute;
                                            background: linear-gradient(135deg, #ec4899, #f43f5e);
                                            color: #ffffff !important;
                                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                                            font-size: 10px;
                                            font-weight: bold;
                                            padding: 2px 6px;
                                            border-radius: 12px;
                                            box-shadow: 0 3px 8px rgba(244, 63, 94, 0.4);
                                            pointer-events: none;
                                            z-index: 99999;
                                            white-space: nowrap;
                                            transform: translate(-50%, -100%);
                                            animation: popIn 0.3s ease-out;
                                            border: 1px solid rgba(255,255,255,0.2);
                                        }
                                        @keyframes popIn {
                                            0% { transform: translate(-50%, -100%) scale(0.6); opacity: 0; }
                                            100% { transform: translate(-50%, -100%) scale(1); opacity: 1; }
                                        }
                                    `;
                                    doc.head.appendChild(style);
                                    
                                    const links = doc.getElementsByTagName('a');
                                    for (let a of links) {
                                        const url = a.getAttribute('href');
                                        if (!url) continue;
                                        
                                        const stat = this.clickMapStats.find(x => x.url === url || url.includes(x.url));
                                        if (stat) {
                                            const bubble = doc.createElement('span');
                                            bubble.className = 'click-overlay-bubble';
                                            bubble.textContent = `${stat.percentage}% (${stat.clicks})`;
                                            
                                            a.style.position = 'relative';
                                            a.appendChild(bubble);
                                        }
                                    }
                                };
                            }, 50);
                        }
                    } catch(e) {}
                },
                
                // Super Admin settings for Tenant registrations
                openCreateTenantModal() {
                    this.tenantForm = { id: null, name: '', generate_dkim: true };
                    this.modals.createTenant = true;
                    this.refreshIcons();
                },
                
                openEditTenantModal(t) {
                    this.tenantForm = { id: t.id, name: t.name, generate_dkim: false };
                    this.modals.createTenant = true;
                    this.refreshIcons();
                },
                
                async submitCreateTenant() {
                    try {
                        const url = this.tenantForm.id ? `/api/tenants/${this.tenantForm.id}` : '/api/tenants';
                        const method = this.tenantForm.id ? 'PUT' : 'POST';
                        const res = await fetch(url, {
                            method: method,
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(this.tenantForm)
                        });
                        if (res.ok) {
                            this.modals.createTenant = false;
                            this.showToast(this.tenantForm.id ? 'Tenant updated successfully' : 'Tenant created successfully');
                            await this.fetchTenants();
                        } else {
                            const err = await res.json();
                            throw new Error(err.detail || 'Failed');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                async deleteTenant(id) {
                    if (!await this.askConfirm('WARNING: Remove this tenant permanently? All lists, campaigns, and subscriber contacts will be lost.', 'Delete Workspace Tenant', true)) return;
                    try {
                        const res = await fetch(`/api/tenants/${id}`, {
                            method: 'DELETE',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            this.showToast('Tenant deleted');
                            await this.fetchTenants();
                        }
                    } catch(e) {}
                },
                
                // Badge color mappings
                getCampaignBadgeClass(status) {
                    if (status === 'sent' || status === 'completed') return 'badge-success';
                    if (status === 'sending') return 'badge-info';
                    if (status === 'paused') return 'badge-warning';
                    if (status === 'queued') return 'badge-warning';
                    if (status === 'cancelled') return 'badge-muted';
                    return 'badge-muted'; // draft
                },
                
                getSubscriberBadgeClass(status) {
                    if (status === 'active') return 'badge-success';
                    if (status === 'unsubscribed') return 'badge-muted';
                    if (status === 'bounced') return 'badge-warning';
                    if (status === 'spam') return 'badge-danger';
                    if (status === 'deferred') return 'badge-warning';
                    if (status === 'failed') return 'badge-danger';
                    if (status === 'pending') return 'badge-info';
                    return 'badge-muted';
                },
                
                calculatePercentage(num, total) {
                    if (!total || total === 0) return 0;
                    return Math.round((num / total) * 100);
                },

                // Reports & Brand Upload additions
                async fetchReportData() {
                    let url = '/api/reports/history';
                    const params = [];
                    if (this.reportsFilterStartDate) {
                        const parts = this.reportsFilterStartDate.split('-');
                        const localStart = new Date(parts[0], parts[1] - 1, parts[2], 0, 0, 0, 0);
                        params.push(`start_date=${localStart.toISOString()}`);
                    }
                    if (this.reportsFilterEndDate) {
                        const parts = this.reportsFilterEndDate.split('-');
                        const localEnd = new Date(parts[0], parts[1] - 1, parts[2], 23, 59, 59, 999);
                        params.push(`end_date=${localEnd.toISOString()}`);
                    }
                    if (params.length > 0) {
                        url += '?' + params.join('&');
                    }
                    try {
                        const res = await fetch(url, { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            this.reportsData = await res.json();
                            this.renderReportsChart();
                        }
                    } catch(e) {
                        console.error('Failed to fetch reports data:', e);
                    }
                },
                
                resetReportsFilters() {
                    this.reportsFilterStartDate = '';
                    this.reportsFilterEndDate = '';
                    this.fetchReportData();
                },
                
                async loadReportSettings() {
                    try {
                        const res = await fetch('/api/reports/settings', { headers: this.getAuthHeaders() });
                        if (res.ok) {
                            const data = await res.json();
                            this.reportsSettings.retention_days = data.retention_days;
                            this.reportsSettings.frequency_hours = data.frequency_hours;
                        }
                    } catch(e) {
                        console.error('Failed to load reports settings:', e);
                    }
                },
                
                async saveReportSettings() {
                    try {
                        const res = await fetch('/api/reports/settings', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                retention_days: this.reportsSettings.retention_days,
                                frequency_hours: this.reportsSettings.frequency_hours
                            })
                        });
                        if (res.ok) {
                            this.showToast('Reports settings updated successfully');
                            await this.loadReportSettings();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to save settings', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                renderReportsChart() {
                    if (this.reportsChartTimeoutId) {
                        clearTimeout(this.reportsChartTimeoutId);
                        this.reportsChartTimeoutId = null;
                    }
                    if (this.reportsChart) {
                        try {
                            this.reportsChart.stop();
                            this.reportsChart.destroy();
                        } catch(e) {}
                        this.reportsChart = null;
                    }
                    this.reportsChartTimeoutId = setTimeout(() => {
                        this.reportsChartTimeoutId = null;
                        
                        // Guard: Only render if we are currently on the reports tab
                        if (this.activeTab !== 'reports') return;
                        
                        const ctx = document.getElementById('reportsChart');
                        if (!ctx) return;
                        
                        // Bulletproof chart instance retrieval to prevent Canvas already in use errors
                        const existingChart = Chart.getChart(ctx);
                        if (existingChart) {
                            try {
                                existingChart.stop();
                                existingChart.destroy();
                            } catch(e) {}
                        }
                        
                        let days = 30;
                        let endingDate = null;
                        if (this.reportsFilterStartDate && this.reportsFilterEndDate) {
                            const start = new Date(this.reportsFilterStartDate);
                            const end = new Date(this.reportsFilterEndDate);
                            end.setHours(23, 59, 59, 999);
                            days = Math.max(1, Math.round((end - start) / (24 * 60 * 60 * 1000)));
                            endingDate = this.reportsFilterEndDate;
                        }
                        
                        const paddedReports = this.preparePaddedHistory(this.reportsData, days, this.reportsTimezone, endingDate);
                        const labels = paddedReports.map(r => r.date);
                        const subsData = paddedReports.map(r => r.subscriber_count);
                        const sentData = paddedReports.map(r => r.emails_sent);
                        const opensData = paddedReports.map(r => r.email_opens);
                        
                        try {
                            this.reportsChart = new Chart(ctx, {
                                type: 'line',
                                data: {
                                    labels: labels.length ? labels : ['No Data'],
                                    datasets: [
                                        {
                                            label: 'Subscribers',
                                            data: subsData.length ? subsData : [0],
                                            borderColor: '#10b981',
                                            backgroundColor: 'rgba(16, 185, 129, 0.05)',
                                            tension: 0.2,
                                            fill: true
                                        },
                                        {
                                            label: 'Emails Sent',
                                            data: sentData.length ? sentData : [0],
                                            borderColor: '#6366f1',
                                            backgroundColor: 'rgba(99, 102, 241, 0.05)',
                                            tension: 0.2,
                                            fill: true
                                        },
                                        {
                                            label: 'Opens',
                                            data: opensData.length ? opensData : [0],
                                            borderColor: '#f59e0b',
                                            backgroundColor: 'rgba(245, 158, 11, 0.05)',
                                            tension: 0.2,
                                            fill: true
                                        }
                                    ]
                                },
                                options: {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    animation: {
                                        duration: 1000,
                                        easing: 'easeOutQuart',
                                        delay: (context) => {
                                            if (context.type === 'data' && context.mode === 'default') {
                                                return context.dataIndex * 17;
                                            }
                                            return 0;
                                        }
                                    },
                                    scales: {
                                        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                                        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
                                    },
                                    plugins: {
                                        legend: { labels: { color: '#f8fafc' } }
                                    }
                                }
                            });
                        } catch(e) {
                            console.error('Failed to create reports chart:', e);
                        }
                    }, 50);
                },
                
                async forceRecordSnapshot() {
                    try {
                        const res = await fetch('/api/reports/record-snapshot', {
                            method: 'POST',
                            headers: this.getAuthHeaders()
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.showToast(data.message);
                            await this.fetchReportData();
                            await this.loadDashboardMetrics();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to record snapshot', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                printReport() {
                    window.print();
                },

                async uploadAppLogo(event) {
                    const file = event.target.files[0];
                    if (!file) return;
                    
                    this.logoFileName = file.name;
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    try {
                        const res = await fetch('/api/auth/branding/logo', {
                            method: 'POST',
                            headers: {
                                'Authorization': `Bearer ${this.token}`
                            },
                            body: formData
                        });
                        
                        if (res.ok) {
                            this.showToast('App branding logo uploaded successfully!');
                            this.logoVersion = Date.now();
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to upload logo', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },

                openPreviewOnlyModal(campaign) {
                    this.editingCampaign = campaign;
                    this.previewIframeSrc = `/api/campaigns/${campaign.id}/preview?mock_name=${encodeURIComponent(this.mockPreviewFields.name)}&mock_email=${encodeURIComponent(this.mockPreviewFields.email)}&_t=${Date.now()}`;
                    this.modals.campaignPreview = true;
                    this.refreshIcons();
                },

                toggleTargetEngagement(star) {
                    if (!this.editingCampaign.target_rules) {
                        this.editingCampaign.target_rules = { tag: '', engagement: [], signup_after: '', signup_before: '' };
                    }
                    if (typeof this.editingCampaign.target_rules.engagement === 'string') {
                        const prev = this.editingCampaign.target_rules.engagement;
                        this.editingCampaign.target_rules.engagement = prev ? [parseInt(prev)] : [];
                    } else if (!this.editingCampaign.target_rules.engagement) {
                        this.editingCampaign.target_rules.engagement = [];
                    }
                    const idx = this.editingCampaign.target_rules.engagement.indexOf(star);
                    if (idx > -1) {
                        this.editingCampaign.target_rules.engagement.splice(idx, 1);
                    } else {
                        this.editingCampaign.target_rules.engagement.push(star);
                    }
                },
                
                openTargetPreviewModal() {
                    this.targetPreviewPage = 1;
                    this.targetPreviewFilter = { search: '', status: '' };
                    this.modals.targetPreview = true;
                    this.fetchTargetPreview();
                },
                
                async fetchTargetPreview() {
                    try {
                        const payload = {
                            list_ids: this.editingCampaign.list_ids || (this.editingCampaign.list_id ? [this.editingCampaign.list_id] : []),
                            target_rules: this.editingCampaign.target_rules || {}
                        };
                        const searchParams = new URLSearchParams({
                            search: this.targetPreviewFilter.search,
                            status: this.targetPreviewFilter.status,
                            page: this.targetPreviewPage,
                            limit: 50
                        });
                        
                        const res = await fetch(`/api/campaigns/${this.editingCampaign.id}/preview-target-subscribers?${searchParams.toString()}`, {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(payload)
                        });
                        if (res.ok) {
                            const data = await res.json();
                            this.targetPreviewData = data.subscribers;
                            this.targetPreviewTotal = data.total;
                            this.refreshIcons();
                        }
                    } catch(e) {
                        console.error('Failed to fetch target preview:', e);
                    }
                },
                
                formatPurgeTime(createdAtStr) {
                    if (!createdAtStr) return 'N/A';
                    const createdDate = new Date(createdAtStr.endsWith('Z') ? createdAtStr : createdAtStr + 'Z');
                    const purgeDate = new Date(createdDate.getTime() + 3 * 24 * 60 * 60 * 1000);
                    const now = new Date();
                    const diffMs = purgeDate - now;
                    if (diffMs <= 0) return 'Expired/Processing';
                    
                    const diffHours = Math.floor(diffMs / (60 * 60 * 1000));
                    if (diffHours >= 24) {
                        const days = Math.floor(diffHours / 24);
                        const hours = diffHours % 24;
                        return `${days}d ${hours}h left`;
                    } else if (diffHours > 0) {
                        const mins = Math.floor((diffMs % (60 * 60 * 1000)) / (60 * 1000));
                        return `${diffHours}h ${mins}m left`;
                    } else {
                        const mins = Math.floor(diffMs / (60 * 1000));
                        return `${mins}m left`;
                    }
                },
                
                editOptInTemplate() {
                    this.isEditingOptIn = true;
                    this.optInSubject = this.tenant.double_opt_in_subject || 'Confirm Your Subscription';
                    
                    const defaultBlocks = [
                        { type: 'heading', text: 'Confirm Your Subscription', align: 'center', color: '#ffffff', size: '28px', padding: '12px 0px' },
                        { type: 'paragraph', text: 'Thank you for signing up! Please click the button below to confirm your subscription and start receiving newsletter updates from us.', align: 'center', color: '#cbd5e1', size: '16px', padding: '10px 0px' },
                        { type: 'button', text: 'Confirm Subscription', url: '{{confirm_url}}', align: 'center', bg_color: '#6366f1', text_color: '#ffffff', border_radius: '8px', padding: '12px 24px' }
                    ];
                    
                    let blocks = this.tenant.double_opt_in_body_blocks;
                    if (typeof blocks === 'string') {
                        try {
                            blocks = JSON.parse(blocks);
                        } catch(e) {
                            blocks = null;
                        }
                    }
                    this.selectedBlockIndex = null;
                    this.editorBlocks = blocks || defaultBlocks;
                    this.switchTab('editor');
                },
                
                async saveOptInTemplate() {
                    const html = compileBlocksToHtml(this.editorBlocks, this.tenant.email_footer_html);
                    try {
                        const res = await fetch('/api/tenants/my', {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                double_opt_in_subject: this.optInSubject,
                                double_opt_in_body_blocks: this.editorBlocks,
                                double_opt_in_body_html: html
                            })
                        });
                        if (res.ok) {
                            this.showToast('Double Opt-In email template saved');
                            await this.fetchTenant();
                            this.switchTab('settings');
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to save template', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                editFooterTemplate() {
                    this.isEditingFooter = true;
                    
                    const defaultBlocks = [
                        { type: 'paragraph', text: 'You are receiving this email because you subscribed to our newsletter list.\nUnsubscribe from this list.', align: 'center', color: '#9ca3af', size: '12px', padding: '10px 0px' }
                    ];
                    
                    let blocks = this.tenant.email_footer_blocks;
                    if (typeof blocks === 'string') {
                        try {
                            blocks = JSON.parse(blocks);
                        } catch(e) {
                            blocks = null;
                        }
                    }
                    this.selectedBlockIndex = null;
                    this.editorBlocks = blocks || defaultBlocks;
                    this.switchTab('editor');
                },
                
                async saveFooterTemplate() {
                    const html = compileBlocksToHtml(this.editorBlocks, null, true);
                    try {
                        const res = await fetch('/api/tenants/my', {
                            method: 'PUT',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify({
                                email_footer_blocks: this.editorBlocks,
                                email_footer_html: html
                            })
                        });
                        if (res.ok) {
                            this.showToast('Custom email footer template saved');
                            await this.fetchTenant();
                            this.switchTab('settings');
                        } else {
                            const err = await res.json();
                            this.showToast(err.detail || 'Failed to save footer template', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    }
                },
                
                openInsertLinkPopup(blockIndex, field) {
                    let id = 'editor-text-input';
                    if (field === 'left') id = 'editor-left-text-input';
                    if (field === 'right') id = 'editor-right-text-input';
                    
                    const el = document.getElementById(id);
                    if (el) {
                        this.lastFocusedInput = {
                            id: id,
                            selectionStart: el.selectionStart,
                            selectionEnd: el.selectionEnd
                        };
                        
                        const selectedText = el.value.substring(el.selectionStart, el.selectionEnd);
                        this.linkForm.text = selectedText || '';
                    } else {
                        this.lastFocusedInput = { id: id, selectionStart: 0, selectionEnd: 0 };
                        this.linkForm.text = '';
                    }
                    this.linkForm.url = 'https://';
                    this.modals.insertLink = true;
                    this.refreshIcons();
                },
                
                submitInsertLink() {
                    if (!this.linkForm.url || this.linkForm.url.trim() === '') {
                        this.showToast('Please enter a target URL', 'warning');
                        return;
                    }
                    
                    const text = this.linkForm.text || 'Link';
                    const url = this.linkForm.url;
                    const linkHtml = `<a href="${url}" style="color: #6366f1; text-decoration: underline;">${text}</a>`;
                    
                    const id = this.lastFocusedInput.id;
                    const el = document.getElementById(id);
                    
                    if (el) {
                        const start = this.lastFocusedInput.selectionStart || 0;
                        const end = this.lastFocusedInput.selectionEnd || 0;
                        const val = el.value;
                        const newVal = val.substring(0, start) + linkHtml + val.substring(end);
                        
                        if (id === 'editor-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].text = newVal;
                        } else if (id === 'editor-left-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].left.text = newVal;
                        } else if (id === 'editor-right-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].right.text = newVal;
                        }
                    } else {
                        if (id === 'editor-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].text = (this.editorBlocks[this.selectedBlockIndex].text || '') + linkHtml;
                        } else if (id === 'editor-left-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].left.text = (this.editorBlocks[this.selectedBlockIndex].left.text || '') + linkHtml;
                        } else if (id === 'editor-right-text-input') {
                            this.editorBlocks[this.selectedBlockIndex].right.text = (this.editorBlocks[this.selectedBlockIndex].right.text || '') + linkHtml;
                        }
                    }
                    
                    this.modals.insertLink = false;
                    this.reRenderCanvas();
                },
                
                async testSmtpConnection() {
                    if (!this.smtpTestEmail) {
                        this.showToast('Please enter a recipient email address for the test', 'warning');
                        return;
                    }
                    this.testingSmtp = true;
                    try {
                        const payload = {
                            name: this.tenant.name,
                            smtp_host: this.tenant.smtp_host,
                            smtp_port: this.tenant.smtp_port ? parseInt(this.tenant.smtp_port) : null,
                            smtp_username: this.tenant.smtp_username,
                            smtp_password: this.tenant.smtp_password,
                            smtp_use_ssl: this.tenant.smtp_use_ssl,
                            smtp_use_tls: this.tenant.smtp_use_tls,
                            direct_send: this.tenant.direct_send,
                            dkim_domain: this.tenant.dkim_domain,
                            dkim_selector: this.tenant.dkim_selector,
                            dkim_private_key: this.tenant.dkim_private_key,
                            bounce_email: this.tenant.bounce_email,
                            test_email: this.smtpTestEmail
                        };
                        const res = await fetch('/api/tenants/test-smtp', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(payload)
                        });
                        const data = await res.json();
                        if (res.ok && data.success) {
                            this.showToast(data.detail);
                        } else {
                            this.showToast(data.detail || 'Test send failed', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    } finally {
                        this.testingSmtp = false;
                    }
                },
                
                async testImapConnection() {
                    this.testingImap = true;
                    try {
                        const payload = {
                            imap_host: this.tenant.imap_host,
                            imap_port: this.tenant.imap_port ? parseInt(this.tenant.imap_port) : null,
                            imap_username: this.tenant.imap_username,
                            imap_password: this.tenant.imap_password,
                            imap_use_ssl: this.tenant.imap_use_ssl
                        };
                        const res = await fetch('/api/tenants/test-imap', {
                            method: 'POST',
                            headers: this.getAuthHeaders(),
                            body: JSON.stringify(payload)
                        });
                        const data = await res.json();
                        if (res.ok && data.success) {
                            this.showToast(data.detail);
                        } else {
                            this.showToast(data.detail || 'IMAP test failed', 'error');
                        }
                    } catch(e) {
                        this.showToast(e.message, 'error');
                    } finally {
                        this.testingImap = false;
                    }
                },
                
                openDnsDetailsModal(recordType, title) {
                    this.dnsDetailRecord = {
                        type: recordType,
                        title: title,
                        sources: this.dnsTestResults[recordType] ? this.dnsTestResults[recordType].sources : { local: [], cloudflare: [], google: [], quad9: [] }
                    };
                    this.modals.dnsDetails = true;
                    this.refreshIcons();
                }
            };
        }
