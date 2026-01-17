// Test script for panel mask functionality
// Run this in the browser console after loading the panel mask

console.log('=== PANEL MASK TEST ===');

// Test some UV coordinates
testPanelMask(0.1, 0.1);  // Top-left
testPanelMask(0.5, 0.5);  // Center
testPanelMask(0.9, 0.9);  // Bottom-right

// Show loaded data
console.log('Panel mask data:', state.panelMask);
console.log('Panel image loaded:', !!state.panelImage);

// List all panels
if (state.panelMask) {
    console.log('All panels:');
    Object.entries(state.panelMask.mapping).forEach(([hex, data]) => {
        console.log(`${hex}: Panel ${data.panel_index} - ${data.panel_id}`);
    });
}