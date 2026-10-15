#include <cstdio>
#include <cstring>
#include "../game/scene_nodes.h"
int main() {
    bool pass=!w101scene::installVerifiedImage(nullptr)&&!w101scene::prepared&&!w101scene::enabled
        &&!strcmp(w101scene::status,"qualification-failed-installation-disabled");
    printf("{\"production_installation_disabled\":%s}\n",pass?"true":"false");
    return pass?0:7;
}
