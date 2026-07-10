using System;
using Xunit;

namespace SteamScreenshotBackup.Tests
{
    // Covers the pure filename/path logic in BackupEngine that has historically
    // regressed in ways only caught by manual harness testing (folder-template
    // desync, fallback app-id parsing). No Steam install or real filesystem needed.
    public class BackupEngineTests
    {
        [Fact]
        public void ConvertName_StandardScreenshot_ProducesReadableTimestampName()
        {
            var (ts, name) = BackupEngine.ConvertName("20260706210532_1.jpg", ScreenshotType.Standard);

            Assert.Equal(new DateTime(2026, 7, 6, 21, 5, 32), ts);
            Assert.Equal("2026-07-06 21.05.32.jpg", name);
        }

        [Fact]
        public void ConvertName_StandardScreenshot_AppendsDisambiguatingSuffixPastFirst()
        {
            var (_, name) = BackupEngine.ConvertName("20260706210532_2.jpg", ScreenshotType.Standard);

            Assert.Equal("2026-07-06 21.05.32 (2).jpg", name);
        }

        [Fact]
        public void ConvertName_HighResScreenshot_StripsLeadingAppId()
        {
            var (ts, name) = BackupEngine.ConvertName("646570_20260707214723_1.png", ScreenshotType.HighRes);

            Assert.Equal(new DateTime(2026, 7, 7, 21, 47, 23), ts);
            Assert.Equal("2026-07-07 21.47.23.png", name);
        }

        // ScreenshotType is internal, so it's kept out of this public Theory's signature
        // (a public member can't expose a less-accessible type) - a bool stands in for it.
        [Theory]
        [InlineData("not_a_screenshot.jpg", false)]
        [InlineData("646570_20260707214723_1.png", false)]   // wrong type for this name shape
        [InlineData("20260706210532_1.jpg", true)]           // wrong type for this name shape
        public void ConvertName_UnrecognizedName_ReturnsNullName(string fileName, bool highRes)
        {
            var (ts, name) = BackupEngine.ConvertName(fileName, highRes ? ScreenshotType.HighRes : ScreenshotType.Standard);

            Assert.Null(name);
            Assert.Equal(DateTime.MinValue, ts);
        }

        [Theory]
        [InlineData("AppID_646570", "646570")]
        [InlineData("Non-Steam App 123456", "123456")]
        [InlineData("Slay the Spire", null)]
        [InlineData("AppID_", null)]
        public void ExtractFallbackAppId_MatchesOnlyGeneratedFallbackNames(string folderName, string expected)
        {
            Assert.Equal(expected, BackupEngine.ExtractFallbackAppId(folderName));
        }

        [Theory]
        [InlineData("Slay the Spire\\2026-07-06 21.05.32.jpg", "{game}", "Slay the Spire")]
        [InlineData("2026\\Slay the Spire\\2026-07-06 21.05.32.jpg", "{yyyy}\\{game}", "Slay the Spire")]
        [InlineData("Slay the Spire\\2026\\2026-07-06 21.05.32.jpg", "{game}\\{yyyy}", "Slay the Spire")]
        [InlineData("Portal 2\\2026-07-06 21.05.32.jpg", "", "Portal 2")]   // blank template falls back to {game}
        public void ExtractGameSegment_FindsGameNameAtTemplatePosition(string rel, string template, string expected)
        {
            Assert.Equal(expected, BackupEngine.ExtractGameSegment(rel, template));
        }

        [Fact]
        public void ExpandTemplate_DefaultTemplate_IsJustTheGameName()
        {
            string result = BackupEngine.ExpandTemplate("{game}", "Slay the Spire", new DateTime(2026, 7, 6));

            Assert.Equal("Slay the Spire", result);
        }

        [Fact]
        public void ExpandTemplate_DateTokens_ExpandFromTheScreenshotTimestamp()
        {
            string result = BackupEngine.ExpandTemplate(
                "{yyyy}\\{MM}\\{dd}\\{game}", "Portal 2", new DateTime(2026, 7, 6));

            Assert.Equal("2026\\07\\06\\Portal 2", result);
        }

        [Theory]
        [InlineData("Foo: Bar?", "Foo Bar")]           // Windows-illegal chars stripped, not replaced
        [InlineData("Mother.", "Mother")]               // trailing dot trimmed (illegal as a folder name)
        [InlineData("  Padded  ", "Padded")]             // leading/trailing spaces trimmed
        public void ExpandTemplate_SanitizesGameNameForTheFileSystem(string game, string expected)
        {
            string result = BackupEngine.ExpandTemplate("{game}", game, new DateTime(2026, 7, 6));

            Assert.Equal(expected, result);
        }

        [Fact]
        public void ExpandTemplate_BlankTemplate_FallsBackToGameOnly()
        {
            string result = BackupEngine.ExpandTemplate("", "Hollow Knight", new DateTime(2026, 7, 6));

            Assert.Equal("Hollow Knight", result);
        }
    }
}
