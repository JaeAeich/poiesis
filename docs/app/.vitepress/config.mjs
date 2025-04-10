import { defineConfig } from "vitepress";

// https://vitepress.dev/reference/site-config
export default defineConfig({
    title: "Poiesis",
    description: "TES on Kubernetes",
    themeConfig: {
        // https://vitepress.dev/reference/default-theme-config
        logo: "/logo/logo.png",
        nav: [{ text: "Home", link: "/" }],
        sidebar: [
            {
                text: "Introduction",
                items: [
                    { text: "TES", link: "/docs/intro/tes" },
                    { text: "Glossary", link: "/docs/intro/glossary" },
                    { text: "Poiesis", link: "/docs/intro/poiesis" },
                ],
            },
            {
                text: "Developer Guide",
                items: [
                    {
                        text: "Architecture",
                        link: "/docs/dev/architecture",
                    },
                    {
                        text: "Starting locally",
                        link: "/docs/dev/starting-locally",
                    },
                ],
            },
            {
                text: "Deployment",
                items: [
                    {
                        text: "Deployment prerequisites",
                        link: "/docs/deploy/prerequisites",
                    },
                    {
                        text: "Deploying Poiesis",
                        link: "/docs/deploy/deploying-poiesis",
                    },
                ],
            },
        ],

        socialLinks: [
            { icon: "github", link: "https://github.com/jaeaeich/poiesis" },
        ],
        footer: {
            message: "Released under the Apache License 2.0.",
            copyright: "Copyright © 2025 jaeaeich (Javed Habib)",
        },
        outline: {
            level: "deep",
            label: "On this page",
        },
    },
    markdown: {
        theme: {
            light: "catppuccin-latte",
            dark: "catppuccin-macchiato",
        },
    },
});
