// Docs sidebar. Imported by config.mjs.
export default [
    {
        text: "Start",
        items: [
            { text: "What is Poiesis", link: "/docs/start/what-is-poiesis" },
            { text: "Quickstart", link: "/docs/start/quickstart" },
            { text: "TES in 5 minutes", link: "/docs/start/tes" },
        ],
    },
    {
        text: "Concepts",
        items: [
            { text: "Tasks and TaskPods", link: "/docs/concepts/tasks" },
            { text: "Task volumes", link: "/docs/concepts/task-volumes" },
            { text: "Storage and staging", link: "/docs/concepts/storage" },
            { text: "Authentication", link: "/docs/concepts/authentication" },
            { text: "Authorization", link: "/docs/concepts/authorization" },
            { text: "API keys", link: "/docs/concepts/api-keys" },
            { text: "Architecture", link: "/docs/concepts/architecture" },
        ],
    },
    {
        text: "Guides",
        items: [
            { text: "Workflow engines", link: "/docs/guides/workflow-engines" },
            { text: "Nextflow end to end", link: "/docs/guides/nextflow" },
            { text: "Keycloak", link: "/docs/guides/keycloak" },
            { text: "Production checklist", link: "/docs/guides/production" },
        ],
    },
    {
        text: "Reference",
        items: [
            { text: "Helm values", link: "/docs/reference/helm-values" },
            { text: "TES API", link: "/docs/reference/api" },
            { text: "Audit log", link: "/docs/reference/audit-log" },
            { text: "Glossary", link: "/docs/reference/glossary" },
        ],
    },
];
