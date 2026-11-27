.PHONY: build test format run bench

build:
	dotnet restore && dotnet build --no-restore -c Release -warnaserror

test: build
	dotnet test --no-build -c Release

format:
	dotnet format

run:
	ASPNETCORE_ENVIRONMENT=Development dotnet run --project src/Rollout.Api

bench:
	dotnet run -c Release --project src/Rollout.Bench -- 200000 42
