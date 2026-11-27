-- Restore by media path because playlist order can change between launches.
local utils = require "mp.utils"
local wanted = os.getenv("FOCUS_RESUME_TRACK")

mp.add_hook("on_load", 5, function()
    if not wanted then return end
    local queue = mp.get_property_native("playlist", {})
    -- The initial URL or playlist file has not expanded yet.
    if #queue == 0 or (#queue == 1 and not queue[1]["playlist-path"]) then return end
    local track = wanted
    wanted = nil
    for i, entry in ipairs(queue) do
        if entry.filename == track then
            mp.set_property_number("playlist-pos", i - 1)
            return
        end
    end
end)

mp.register_event("file-loaded", function()
    local info = {
        track = mp.get_property("path"),
        title = mp.get_property("media-title", "")
    }
    mp.msg.info("FOCUS_TRACK " .. utils.format_json(info))
end)
