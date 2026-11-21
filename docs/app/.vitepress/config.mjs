import { defineConfig } from "vitepress";
import sidebar from "./sidebar.mjs";

// https://vitepress.dev/reference/site-config
export default defineConfig({
    title: "Poiesis",
    description: "A GA4GH Task Execution Service for Kubernetes",
    head: [
        ["link", { rel: "icon", href: "/logo/favicon.ico" }],
        ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
        ["link", { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: "" }],
        [
            "link",
            {
                rel: "stylesheet",
                href: "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap",
            },
        ],
    ],
    themeConfig: {
        // https://vitepress.dev/reference/default-theme-config
        logo: "/logo/logo.png",
        nav: [
            { text: "Docs", link: "/docs/start/what-is-poiesis", activeMatch: "^/docs/" },
            { text: "Deploy", link: "/deploy" },
        ],
        // docs pages only; home and deploy are full width
        sidebar: { "/docs/": sidebar },
        search: {
            provider: "local",
        },
        socialLinks: [
            { icon: "github", link: "https://github.com/jaeaeich/poiesis" },
        ],
        outline: {
            level: "deep",
            label: "On this page",
        },
        editLink: {
            pattern:
                "https://github.com/jaeaeich/poiesis/edit/main/docs/app/:path",
            text: "Edit this page on GitHub",
        },
    },
    markdown: {
        theme: {
            light: "github-light",
            dark: "github-dark",
        },
    },
    ignoreDeadLinks: [
        // ignore all localhost links
        /^https?:\/\/localhost/,
        (url) => {
            return url.toLowerCase().includes("ignore");
        },
    ],
});
