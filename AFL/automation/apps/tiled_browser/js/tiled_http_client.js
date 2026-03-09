(function attachTiledHttpClient(global) {
    const DEFAULT_FIELD_CANDIDATES = {
        task_name: ['task_name', 'attrs.task_name'],
        driver_name: ['driver_name', 'attrs.driver_name'],
        sample_uuid: ['sample_uuid', 'attrs.sample_uuid'],
        sample_name: ['sample_name', 'attrs.sample_name'],
        AL_campaign_name: ['AL_campaign_name', 'attrs.AL_campaign_name'],
        AL_uuid: ['AL_uuid', 'attrs.AL_uuid'],
        AL_components: ['AL_components', 'attrs.AL_components'],
        meta_started: ['meta.started', 'attrs.meta.started'],
        meta_ended: ['meta.ended', 'attrs.meta.ended'],
        run_time_minutes: ['meta.run_time_minutes', 'attrs.meta.run_time_minutes']
    };

    function getAuthToken() {
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'access_token_cookie') {
                return value;
            }
        }
        return null;
    }

    async function authenticatedFetch(url, options = {}) {
        const token = getAuthToken();
        const headers = { ...(options.headers || {}) };
        if (token) {
            headers.Authorization = `Bearer ${token}`;
        }
        return fetch(url, { ...options, headers });
    }

    function withTrailingSlash(url) {
        return url.endsWith('/') ? url : `${url}/`;
    }

    function joinUrl(base, path) {
        if (!path) return base;
        const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
        const normalizedPath = path.startsWith('/') ? path.slice(1) : path;
        return `${normalizedBase}/${normalizedPath}`;
    }

    function parseJsonValue(value) {
        try {
            return JSON.parse(value);
        } catch (_err) {
            return value;
        }
    }

    function getByPath(obj, path) {
        if (!obj || !path) return null;
        const parts = path.split('.');
        let current = obj;
        for (const part of parts) {
            if (current === null || current === undefined) return null;
            current = current[part];
        }
        return current;
    }

    function uniqueValues(values) {
        return Array.from(new Set(values.filter(v => v !== null && v !== undefined && v !== '')));
    }

    function candidatePathsForField(field, candidatesMap = DEFAULT_FIELD_CANDIDATES) {
        const mapped = candidatesMap[field];
        if (Array.isArray(mapped) && mapped.length > 0) {
            return mapped;
        }
        if (typeof field === 'string' && field.length > 0) {
            if (field.startsWith('attrs.')) {
                return [field, field.slice('attrs.'.length)];
            }
            return [field, `attrs.${field}`];
        }
        return [];
    }

    function canonicalPath(field, candidatesMap = DEFAULT_FIELD_CANDIDATES) {
        const candidates = candidatePathsForField(field, candidatesMap);
        const preferred = candidates.find(path => path.startsWith('attrs.'));
        return preferred || candidates[0] || field;
    }

    function alternatePath(field, candidatesMap = DEFAULT_FIELD_CANDIDATES) {
        const candidates = candidatePathsForField(field, candidatesMap);
        if (candidates.length < 2) return null;
        const canonical = canonicalPath(field, candidatesMap);
        return candidates.find(path => path !== canonical) || null;
    }

    function resolveMetadataValue(metadata, logicalKey, candidatesMap = DEFAULT_FIELD_CANDIDATES) {
        const candidates = candidatePathsForField(logicalKey, candidatesMap);
        for (const path of candidates) {
            const value = getByPath(metadata, path);
            if (value !== null && value !== undefined) {
                return value;
            }
        }
        return null;
    }

    function buildSearchParams({
        offset = 0,
        limit = 50,
        sortModel = [],
        queryRows = [],
        quickFilters = {},
        candidatesMap = DEFAULT_FIELD_CANDIDATES,
        useAlternate = false,
        fields = ['metadata', 'structure_family']
    } = {}) {
        const params = new URLSearchParams();
        params.set('page[offset]', String(offset));
        params.set('page[limit]', String(limit));

        if (Array.isArray(fields)) {
            for (const field of fields) {
                params.append('fields', field);
            }
        }

        const sortTokens = [];
        for (const item of sortModel || []) {
            const colId = item.colId || item.field;
            const direction = item.sort;
            if (!colId || (direction !== 'asc' && direction !== 'desc')) continue;
            const path = useAlternate ? (alternatePath(colId, candidatesMap) || canonicalPath(colId, candidatesMap)) : canonicalPath(colId, candidatesMap);
            sortTokens.push(direction === 'desc' ? `-${path}` : path);
        }
        if (sortTokens.length > 0) {
            params.set('sort', sortTokens.join(','));
        }

        for (const query of queryRows || []) {
            const key = query.field;
            const value = query.value;
            if (!key || value === null || value === undefined || value === '') continue;
            const path = useAlternate ? (alternatePath(key, candidatesMap) || canonicalPath(key, candidatesMap)) : canonicalPath(key, candidatesMap);
            params.append('filter[contains][condition][key]', path);
            params.append('filter[contains][condition][value]', JSON.stringify(value));
        }

        for (const [key, values] of Object.entries(quickFilters || {})) {
            const cleaned = uniqueValues(Array.isArray(values) ? values : [values]);
            if (cleaned.length === 0) continue;
            const path = useAlternate ? (alternatePath(key, candidatesMap) || canonicalPath(key, candidatesMap)) : canonicalPath(key, candidatesMap);
            params.append('filter[in][condition][key]', path);
            params.append('filter[in][condition][value]', JSON.stringify(cleaned));
        }

        return params;
    }

    function buildDistinctParams({ metadataKeys = [], activeFilters = {}, candidatesMap = DEFAULT_FIELD_CANDIDATES } = {}) {
        const params = new URLSearchParams();
        params.set('counts', 'true');

        for (const key of metadataKeys) {
            const paths = candidatePathsForField(key, candidatesMap);
            for (const path of paths) {
                params.append('metadata', path);
            }
        }

        for (const [key, values] of Object.entries(activeFilters || {})) {
            const cleaned = uniqueValues(Array.isArray(values) ? values : [values]);
            if (cleaned.length === 0) continue;
            const paths = candidatePathsForField(key, candidatesMap);
            for (const path of paths) {
                params.append('filter[in][condition][key]', path);
                params.append('filter[in][condition][value]', JSON.stringify(cleaned));
            }
        }

        return params;
    }

    function mergeSearchData(primaryData, secondaryData) {
        const byId = new Map();
        for (const item of primaryData || []) {
            if (item && item.id) byId.set(item.id, item);
        }
        for (const item of secondaryData || []) {
            if (item && item.id && !byId.has(item.id)) {
                byId.set(item.id, item);
            }
        }
        return Array.from(byId.values());
    }

    function normalizeSearchResponse(payload) {
        const data = Array.isArray(payload?.data) ? payload.data : [];
        const count = Number(payload?.meta?.count || 0);
        return { data, totalCount: Number.isFinite(count) ? count : 0 };
    }

    async function createClientFromConfig(config) {
        const base = withTrailingSlash(config.tiled_server || '');
        const apiKey = config.tiled_api_key;
        if (!base || !apiKey) {
            throw new Error('Missing tiled_server or tiled_api_key');
        }

        async function probeDirectMode() {
            try {
                const probeParams = new URLSearchParams();
                probeParams.set('page[offset]', '0');
                probeParams.set('page[limit]', '1');
                const probeUrl = `${joinUrl(base, 'api/v1/search/')}?${probeParams.toString()}`;
                const response = await fetch(probeUrl, {
                    method: 'GET',
                    headers: {
                        Authorization: `Apikey ${apiKey}`
                    }
                });
                return response.ok;
            } catch (_error) {
                return false;
            }
        }

        async function tiledFetch(path, { params, headers = {}, signal, responseType = 'json' } = {}) {
            const url = joinUrl(base, path);
            const finalUrl = params ? `${url}?${params.toString()}` : url;
            const response = await fetch(finalUrl, {
                method: 'GET',
                headers: {
                    Authorization: `Apikey ${apiKey}`,
                    ...headers
                },
                signal
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(`Tiled request failed (${response.status}): ${text || response.statusText}`);
            }
            if (responseType === 'text') {
                return response.text();
            }
            if (responseType === 'blob') {
                return response.blob();
            }
            return response.json();
        }

        async function legacySearch({ queryRows = [], quickFilters = {}, sortModel = [], offset = 0, limit = 50 }, { signal } = {}) {
            const params = new URLSearchParams({
                queries: JSON.stringify(queryRows || []),
                filters: JSON.stringify(quickFilters || {}),
                sort: JSON.stringify(sortModel || []),
                offset: String(offset),
                limit: String(limit)
            });
            const response = await authenticatedFetch(`/tiled_search?${params}`, { signal });
            if (!response.ok) {
                throw new Error(`Legacy search failed (${response.status})`);
            }
            return response.json();
        }

        async function legacyDistinct(field, { signal } = {}) {
            const params = new URLSearchParams({ field });
            const response = await authenticatedFetch(`/tiled_get_distinct_values?${params}`, { signal });
            if (!response.ok) {
                throw new Error(`Legacy distinct failed (${response.status})`);
            }
            return response.json();
        }

        async function legacyMetadata(entryId, { signal } = {}) {
            const params = new URLSearchParams({ entry_id: entryId });
            const response = await authenticatedFetch(`/tiled_get_metadata?${params}`, { signal });
            if (!response.ok) {
                throw new Error(`Legacy metadata failed (${response.status})`);
            }
            return response.json();
        }

        async function legacyFull(entryId, { responseType = 'json', signal } = {}) {
            if (responseType === 'text') {
                const params = new URLSearchParams({ entry_id: entryId });
                const response = await authenticatedFetch(`/tiled_get_data?${params}`, { signal });
                if (!response.ok) {
                    throw new Error(`Legacy data failed (${response.status})`);
                }
                return response.json();
            }
            const params = new URLSearchParams({ entry_id: entryId });
            const response = await authenticatedFetch(`/tiled_get_full_json?${params}`, { signal });
            if (!response.ok) {
                throw new Error(`Legacy full json failed (${response.status})`);
            }
            return response.json();
        }

        const useProxy = !(await probeDirectMode());

        async function search(params, { path = '', signal, legacyPayload = null } = {}) {
            if (useProxy) {
                if (!legacyPayload) {
                    throw new Error('Legacy payload required for proxy search mode');
                }
                return legacySearch(legacyPayload, { signal });
            }
            const endpoint = path ? `api/v1/search/${path}` : 'api/v1/search/';
            return tiledFetch(endpoint, { params, signal, responseType: 'json' });
        }

        async function distinct(params, { path = '', signal, legacyField = null } = {}) {
            if (useProxy) {
                const fallbackField = legacyField || (params && params.getAll('metadata')[0]) || '';
                const normalizedField = fallbackField.startsWith('attrs.') ? fallbackField.slice('attrs.'.length) : fallbackField;
                return legacyDistinct(normalizedField, { signal });
            }
            const endpoint = path ? `api/v1/distinct/${path}` : 'api/v1/distinct/';
            return tiledFetch(endpoint, { params, signal, responseType: 'json' });
        }

        async function metadata(entryId, { signal } = {}) {
            if (useProxy) {
                const payload = await legacyMetadata(entryId, { signal });
                if (payload.status === 'error') {
                    throw new Error(payload.message || `Entry ${entryId} not found`);
                }
                return {
                    data: {
                        id: entryId,
                        attributes: { metadata: payload.metadata || {} },
                        links: {}
                    }
                };
            }
            return tiledFetch(`api/v1/metadata/${entryId}`, { signal, responseType: 'json' });
        }

        async function full(link, { format = 'application/json', signal, responseType = 'json', entryId = null } = {}) {
            if (useProxy) {
                if (!entryId) {
                    throw new Error('entryId is required for proxy full-data mode');
                }
                const payload = await legacyFull(entryId, { responseType, signal });
                if (payload.status === 'error') {
                    throw new Error(payload.message || `Failed to load full data for ${entryId}`);
                }
                if (responseType === 'text') {
                    return payload.html || '';
                }
                return payload.data || {};
            }

            // Full-link URLs often point to a different host/port than this web app.
            // If cross-origin, use same-origin proxy endpoints to avoid browser CORS failures.
            if (entryId) {
                try {
                    const fullTarget = new URL(link, window.location.href);
                    if (fullTarget.origin !== window.location.origin) {
                        const payload = await legacyFull(entryId, { responseType, signal });
                        if (payload.status === 'error') {
                            throw new Error(payload.message || `Failed to load full data for ${entryId}`);
                        }
                        if (responseType === 'text') {
                            return payload.html || '';
                        }
                        return payload.data || {};
                    }
                } catch (_urlError) {
                    // If URL parsing fails, continue and attempt direct fetch below.
                }
            }

            const params = new URLSearchParams();
            if (format) params.set('format', format);
            const fullUrl = `${link}${link.includes('?') ? '&' : '?'}${params.toString()}`;
            try {
                const response = await fetch(fullUrl, {
                    method: 'GET',
                    headers: {
                        Authorization: `Apikey ${apiKey}`
                    },
                    signal
                });
                if (!response.ok) {
                    const text = await response.text();
                    throw new Error(`Tiled full-link request failed (${response.status}): ${text || response.statusText}`);
                }
                if (responseType === 'text') return response.text();
                if (responseType === 'blob') return response.blob();
                return response.json();
            } catch (error) {
                // Last-chance fallback for CORS/network issues in direct mode.
                if (entryId) {
                    const payload = await legacyFull(entryId, { responseType, signal });
                    if (payload.status === 'error') {
                        throw new Error(payload.message || `Failed to load full data for ${entryId}`);
                    }
                    if (responseType === 'text') {
                        return payload.html || '';
                    }
                    return payload.data || {};
                }
                throw error;
            }
        }

        return {
            base,
            apiKey,
            useProxy,
            mode: useProxy ? 'proxy' : 'direct',
            search,
            distinct,
            metadata,
            full
        };
    }

    async function loadConfig() {
        const response = await authenticatedFetch('/tiled_config');
        const payload = await response.json();
        if (!response.ok || payload.status === 'error') {
            const message = payload?.message || `HTTP ${response.status}`;
            throw new Error(message);
        }
        return {
            tiled_server: payload.tiled_server,
            tiled_api_key: payload.tiled_api_key
        };
    }

    global.TiledHttpClient = {
        DEFAULT_FIELD_CANDIDATES,
        getAuthToken,
        authenticatedFetch,
        loadConfig,
        createClientFromConfig,
        buildSearchParams,
        buildDistinctParams,
        mergeSearchData,
        normalizeSearchResponse,
        parseJsonValue,
        getByPath,
        candidatePathsForField,
        canonicalPath,
        alternatePath,
        resolveMetadataValue,
        uniqueValues
    };
})(window);
