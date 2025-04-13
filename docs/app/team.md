---
layout: page
---

<script setup>
import {
  VPTeamPage,
  VPTeamPageTitle,
  VPTeamMembers
} from 'vitepress/theme'

const members = [
  {
    avatar: 'https://avatars.githubusercontent.com/jaeaeich',
    name: 'Javed Habib',
    title: 'Author',
    org: 'Poiesis',
    orgLink: 'https://github.com/jaeaeich/poiesis',
    desc: `
      Started as an '<i>Oh, I can build that in a weekend</i>' project...
      and here we are, months later.
    `,
    links: [
      { icon: 'github', link: 'https://github.com/jaeaeich' },
      { icon: 'twitter', link: 'https://twitter.com/jaeaeich' },
      { icon: 'linkedin', link: 'https://www.linkedin.com/in/javed-habib/' }
    ],
  }
]
</script>

<VPTeamPage>
  <VPTeamPageTitle>
    <template #title>
        Team
    </template>
    <template #lead>
      Poiesis is an <i> open source project</i>, shoot a message for more info!
    </template>
  </VPTeamPageTitle>
  <VPTeamMembers :members="members" />
</VPTeamPage>
