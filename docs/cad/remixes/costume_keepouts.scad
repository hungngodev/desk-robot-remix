// CC0 original code. Millimeters in one measured assembly coordinate frame.
// Conservative AABB screen only; not a fitted costume or physical acceptance.
// Supply swept costume boxes expanded for tolerance, play, and deflection,
// and measured protected volumes expanded for the required clearance.
// Each box is [minimum_xyz, maximum_xyz]; touching is rejected.
function costume_interfaces() = [
    "camera", "tof0", "tof1", "tof2", "tof3", "tof4", "tof5", "tof6", "tof7",
    "pdm_mic", "speaker", "sense_vent", "wroom_vent", "amp_vent"
];
function valid_point(p) = is_list(p) && len(p)==3 &&
    len([for(v=p) if(is_num(v) && v-v==0) v])==3;
function valid_box(b) = is_list(b) && len(b)==2 &&
    valid_point(b[0]) && valid_point(b[1]) &&
    len([for(i=[0:2]) if(b[0][i]<b[1][i]) i])==3;
function separated(a,b) = len([for(i=[0:2])
    if(a[1][i]<b[0][i] || b[1][i]<a[0][i]) i])>0;

// keepouts: ordered [interface_name, [box, ...]] records; no default dimensions.
// Supply all swept accessory envelopes, not just the nominal installed pose.
module costume_keepout_guard(swept, keepouts) {
    required=costume_interfaces();
    assert(is_list(swept) && len(swept)>0, "Missing costume swept envelopes");
    assert(is_list(keepouts) && len(keepouts)==len(required),
           "Missing or extra costume keepout interfaces");
    for(a=swept) assert(valid_box(a), "Invalid costume swept box");
    for(i=[0:len(required)-1]) {
        entry=keepouts[i];
        assert(is_list(entry) && len(entry)==2 && entry[0]==required[i],
               str("Missing or misordered keepout: ",required[i]));
        assert(is_list(entry[1]) && len(entry[1])>0,
               str("Missing measured boxes: ",required[i]));
        for(b=entry[1]) {
            assert(valid_box(b), str("Invalid keepout: ",required[i]));
            for(a=swept) assert(separated(a,b), str("Costume occlusion: ",required[i]));
        }
    }
    children();
}
