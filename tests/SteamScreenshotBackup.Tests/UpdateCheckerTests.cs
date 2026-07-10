using Xunit;

namespace SteamScreenshotBackup.Tests
{
    public class UpdateCheckerTests
    {
        [Theory]
        [InlineData("v3.11.0", "3.10.0", "3.11.0")]   // newer, "v" prefix stripped
        [InlineData("V3.11.0", "3.10.0", "3.11.0")]   // uppercase "V" prefix also stripped
        [InlineData("3.11.0", "3.10.0", "3.11.0")]    // no prefix at all
        [InlineData("v4.0.0", "3.10.0", "4.0.0")]     // major bump
        public void NewerVersionOrNull_NewerTag_ReturnsCleanedVersion(string tag, string current, string expected)
        {
            Assert.Equal(expected, UpdateChecker.NewerVersionOrNull(tag, current));
        }

        [Theory]
        [InlineData("v3.10.0", "3.10.0")]   // same version
        [InlineData("v3.9.2", "3.10.0")]    // older
        [InlineData("v3.9.9", "3.10.0")]    // older, higher patch than current's patch but lower minor
        public void NewerVersionOrNull_NotNewer_ReturnsNull(string tag, string current)
        {
            Assert.Null(UpdateChecker.NewerVersionOrNull(tag, current));
        }

        [Theory]
        [InlineData(null, "3.10.0")]
        [InlineData("not-a-version", "3.10.0")]
        [InlineData("v3.11.0", "not-a-version")]
        [InlineData("v3.11.0", null)]
        public void NewerVersionOrNull_UnparseableInput_ReturnsNullRatherThanThrowing(string tag, string current)
        {
            Assert.Null(UpdateChecker.NewerVersionOrNull(tag, current));
        }
    }
}
